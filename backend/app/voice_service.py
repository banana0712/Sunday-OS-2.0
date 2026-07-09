"""
SundayOS 语音服务 v1 — 豆包 ASR + TTS
- ASR：豆包流式语音识别 2.0（WebSocket）
- TTS：豆包声音合成 2.0 / 声音克隆（HTTP POST）
- 支持自然语言情感控制（context_texts）
"""
import os
import json
import base64
import asyncio
import gzip
import struct
import uuid
import logging
import requests
import websockets

logger = logging.getLogger(__name__)

# ============================================================
# 豆包 API 常量
# ============================================================
DOUBAO_ASR_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
DOUBAO_TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"

# 消息类型标志（自定义二进制协议）
MSG_FULL_REQUEST = 0b0001   # 首包：JSON 参数
MSG_AUDIO_ONLY = 0b0010     # 后续包：纯音频数据
MSG_FULL_RESPONSE = 0b1001  # 服务端返回结果
MSG_ERROR = 0b1111          # 错误

# 序列化/压缩标志
SERIALIZATION_JSON = 0b0001
COMPRESSION_GZIP = 0b0001
COMPRESSION_NONE = 0b0000


class VoiceService:
    """Sunday 语音服务：ASR（语音识别）+ TTS（语音合成）"""

    def __init__(self):
        self.asr_app_key = os.environ.get("DOUBAO_ASR_APP_KEY", "")
        self.asr_access_key = os.environ.get("DOUBAO_ASR_ACCESS_KEY", "")
        self.asr_resource_id = os.environ.get(
            "DOUBAO_ASR_RESOURCE_ID", "volc.seedasr.sauc.duration"
        )
        self.tts_app_id = os.environ.get("DOUBAO_TTS_APP_ID", "")
        self.tts_access_key = os.environ.get("DOUBAO_TTS_ACCESS_KEY", "")
        self.tts_speaker = os.environ.get("DOUBAO_TTS_SPEAKER", "zh_female_vv_uranus_bigtts")
        self.tts_resource_id = self._get_tts_resource_id()

    def is_available(self) -> bool:
        """检查语音服务是否可用"""
        return bool(self.asr_app_key and self.tts_app_id and self.tts_speaker)

    def _get_tts_resource_id(self) -> str:
        """根据 Speaker ID 判断 TTS 模型"""
        if self.tts_speaker.startswith("S_"):
            return "seed-icl-2.0"       # 声音克隆
        elif "_uranus_" in self.tts_speaker or self.tts_speaker.startswith("saturn_"):
            return "seed-tts-2.0"       # 官方 2.0 预设
        else:
            return "seed-tts-1.0"       # 官方 1.0

    # ========== ASR ==========

    async def transcribe(self, audio_data: bytes, audio_format: str = "ogg") -> str:
        """
        语音转文字（流式识别）。30s 超时兜底，避免 WebSocket 挂死导致无响应。

        Args:
            audio_data: 原始音频数据（ogg/mp3/wav/pcm）
            audio_format: 音频格式（pcm 时直接发送，其他格式先转码）

        Returns:
            识别的文字（可能为空字符串）
        """
        try:
            return await asyncio.wait_for(
                self._transcribe_inner(audio_data, audio_format),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.error("ASR 转写超时（30s）")
            return ""
        except Exception as e:
            logger.error(f"ASR WebSocket 错误: {e}")
            return ""

    async def _transcribe_inner(self, audio_data: bytes, audio_format: str) -> str:
        # 非 PCM 格式先转码
        if audio_format != "pcm":
            audio_data = await self._convert_to_pcm(audio_data, audio_format)

        request_id = str(uuid.uuid4())
        headers = {
            "X-Api-App-Key": self.asr_app_key,
            "X-Api-Access-Key": self.asr_access_key,
            "X-Api-Resource-Id": self.asr_resource_id,
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }

        results = []
        async with websockets.connect(
            DOUBAO_ASR_WS_URL,
            additional_headers=headers,
            open_timeout=10,
            close_timeout=3,
        ) as ws:
            # 发送首包（Full Client Request）
            first_request = json.dumps({
                "user": {"uid": "sundayos"},
                "audio": {
                    "format": "pcm",
                    "rate": 16000,
                    "bits": 16,
                    "channel": 1,
                    "language": "zh-CN",
                },
                "request": {
                    "model_name": "bigmodel",
                    "enable_itn": True,
                    "enable_punc": True,
                }
            })
            await self._send_frame(ws, MSG_FULL_REQUEST, first_request.encode())

            # 分片发送音频（每 200ms 一包 ≈ 6400 bytes）
            chunk_size = 6400
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                await self._send_frame(ws, MSG_AUDIO_ONLY, chunk)
                # 非阻塞尝试接收中间结果
                try:
                    result = await asyncio.wait_for(ws.recv(), timeout=0.05)
                    text = self._parse_response(result)
                    if text:
                        results.append(text)
                except asyncio.TimeoutError:
                    pass

            # 等待最终结果
            try:
                while True:
                    result = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    text = self._parse_response(result)
                    if text:
                        results.append(text)
            except asyncio.TimeoutError:
                pass

        return results[-1] if results else ""

    def _parse_response(self, raw_data: bytes) -> str:
        """解析 ASR 返回的二进制帧"""
        try:
            header = struct.unpack(">I", raw_data[:4])[0]
            payload_size = struct.unpack(">I", raw_data[4:8])[0]
            payload = raw_data[8:8 + payload_size]

            compression = (header >> 4) & 0x0F
            if compression == COMPRESSION_GZIP:
                payload = gzip.decompress(payload)

            msg_type = header & 0x0F
            if msg_type == MSG_FULL_RESPONSE:
                result = json.loads(payload.decode())
                return result.get("result", {}).get("text", "")
            elif msg_type == MSG_ERROR:
                error = json.loads(payload.decode())
                logger.warning(f"ASR error: {error}")
        except Exception as e:
            logger.warning(f"解析 ASR 响应失败: {e}")
        return ""

    async def _send_frame(self, ws, msg_type: int, payload: bytes):
        """发送 WebSocket 二进制帧"""
        compressed = gzip.compress(payload) if len(payload) > 100 else payload
        compression = COMPRESSION_GZIP if len(payload) > 100 else COMPRESSION_NONE

        serialization = SERIALIZATION_JSON if msg_type == MSG_FULL_REQUEST else 0
        header = (0x10 << 24) | (serialization << 8) | (compression << 4) | msg_type
        header_bytes = struct.pack(">I", header)
        size_bytes = struct.pack(">I", len(compressed))

        await ws.send(header_bytes + size_bytes + compressed)

    async def _convert_to_pcm(self, audio_data: bytes, fmt: str) -> bytes:
        """用 ffmpeg 转码为 16kHz mono PCM"""
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", "pipe:0",
            "-ar", "16000", "-ac", "1", "-f", "s16le",
            "-acodec", "pcm_s16le", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=audio_data)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 转码失败: {stderr.decode()[:200]}")
        return stdout

    # ========== TTS ==========

    async def synthesize(self, text: str, emotion: str = "default") -> bytes:
        """
        文字转语音，返回 MP3 音频数据。

        长文本会自动按句分段合成后拼接，避免触发豆包
        「input length too long (400)」的单次字数上限。

        Args:
            text: 要合成的文字
            emotion: 情感标签 (default/sweet/gentle/excited/lazy/shy/comfort)

        Returns:
            MP3 音频 bytes
        """
        context_text = EMOTION_PROMPTS.get(emotion, "")
        chunks = self.split_for_tts(text, max_chars=200)

        # 只有一段：直接合成，省去拼接
        if len(chunks) == 1:
            return await self._synthesize_chunk(chunks[0], context_text)

        # 多段：逐段合成再拼接
        audio_parts = []
        for chunk in chunks:
            audio = await self._synthesize_chunk(chunk, context_text)
            audio_parts.append(audio)
        return b"".join(audio_parts)

    async def _synthesize_chunk(self, text: str, context_text: str = "") -> bytes:
        """对单段文本调用豆包 TTS，返回 MP3 bytes"""
        additions = {}
        if context_text:
            additions["context_texts"] = [context_text]
        if self.tts_speaker.startswith("S_"):
            additions["model_type"] = 4  # 克隆模型需要

        payload = {
            "user": {"uid": "sundayos"},
            "req_params": {
                "text": text,
                "speaker": self.tts_speaker,
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": 24000,
                },
                "additions": json.dumps(additions) if additions else "{}",
            },
        }

        headers = {
            "Content-Type": "application/json",
            "X-Api-App-Id": self.tts_app_id,
            "X-Api-Access-Key": self.tts_access_key,
            "X-Api-Resource-Id": self.tts_resource_id,
        }

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(DOUBAO_TTS_URL, headers=headers, json=payload, timeout=30)
        )
        response.raise_for_status()

        audio_chunks = []
        for line in response.text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue

            code = parsed.get("code")
            if code == 0 and "data" in parsed:
                audio_chunks.append(base64.b64decode(parsed["data"]))
            elif code == 20000000:
                break  # 流结束
            elif code is not None and code != 0:
                raise RuntimeError(f"TTS error: code={code}")

        if not audio_chunks:
            raise RuntimeError("TTS returned no audio data")

        return b"".join(audio_chunks)

    async def synthesize_with_emotions(self, segments: list[tuple[str, str]]) -> bytes:
        """
        逐句合成，每句可有不同情感。

        Args:
            segments: [(text, emotion), ...]

        Returns:
            拼接后的 MP3 音频
        """
        audio_parts = []
        for seg_text, emotion in segments:
            context_text = EMOTION_PROMPTS.get(emotion, "")
            audio = await self._synthesize_chunk(seg_text, context_text)
            audio_parts.append(audio)
        return b"".join(audio_parts)

    @staticmethod
    def split_for_tts(text: str, max_chars: int = 300) -> list[str]:
        """
        按句号/感叹号/问号分段，保证每段不超过 max_chars。
        若单句本身超过 max_chars，再做硬切兜底，彻底避免超长报错。
        """
        import re
        sentences = re.split(r'(?<=[。！？\n])\s*', text)
        chunks = []
        current = ""
        for s in sentences:
            s = s.strip()
            if not s:
                continue
            # 单句本身超长：先硬切成不超过 max_chars 的小段
            if len(s) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                for i in range(0, len(s), max_chars):
                    chunks.append(s[i:i + max_chars])
                continue
            if len(current) + len(s) <= max_chars:
                current += s
            else:
                chunks.append(current)
                current = s
        if current:
            chunks.append(current)
        return chunks or [text]


# ============================================================
# 情感提示词映射
# ============================================================
EMOTION_PROMPTS = {
    "sweet": "用甜蜜撒娇的声音，像在跟男朋友撒娇，语调上扬很开心，尾音微微拖长",
    "gentle": "用温柔舒缓的声音，轻声细语地说话，让人感到安心和温暖",
    "excited": "用非常激动兴奋的语气，声音明亮上扬，开心到像要跳起来",
    "lazy": "用慵懒随意的声音，软绵绵的很放松，像刚睡醒在被窝里聊天，语速慢一点",
    "shy": "用害羞的声音，语调微微上扬，声音轻一点，带着一点不好意思",
    "comfort": "用温柔心疼的声音，轻声安慰，像在抱抱对方，声音柔软温暖",
    "default": "用自然甜美的声音，像和朋友聊天一样，语调温柔上扬",
}


# 全局单例
voice_service = VoiceService()
