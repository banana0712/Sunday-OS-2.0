"""
SundayOS 语音服务 v2 — 豆包异步 ASR + TTS + MiniMax 音乐生成
- ASR：异步 HTTP（submit + 轮询 query）
- TTS：HTTP 流式合成（unidirectional）
- 唱歌：MiniMax Music API（music-2.6-free 原创 + music-cover-free 翻唱）
"""
import os
import json
import base64
import asyncio
import uuid
import logging
import httpx

logger = logging.getLogger(__name__)

# MiniMax Music API
MINIMAX_MUSIC_URL = "https://api.minimaxi.com/v1/music_generation"
MINIMAX_COVER_PREPROCESS_URL = "https://api.minimaxi.com/v1/music_cover_preprocess"

# ============================================================
# 豆包 API 常量（异步 ASR + 流式 TTS）
# ============================================================
DOUBAO_ASR_SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
DOUBAO_ASR_QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"
DOUBAO_TTS_URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"

# ASR 轮询间隔（秒）
ASR_POLL_INTERVAL = 2
# ASR 最大等待时间（秒）
ASR_MAX_WAIT = 60


class VoiceService:
    """Sunday 语音服务 v2：异步 ASR + 流式 TTS"""

    def __init__(self):
        # ASR 配置
        self.asr_api_key = os.environ.get("DOUBAO_ASR_API_KEY", "")
        self.asr_resource_id = os.environ.get(
            "DOUBAO_ASR_RESOURCE_ID", "volc.seedasr.auc"
        )
        # TTS 配置
        self.tts_api_key = os.environ.get("DOUBAO_TTS_API_KEY", "")
        self.tts_resource_id = os.environ.get(
            "DOUBAO_TTS_RESOURCE_ID", "seed-tts-2.0"
        )
        self.tts_speaker = os.environ.get(
            "DOUBAO_TTS_SPEAKER", "zh_female_vv_uranus_bigtts"
        )
        # MiniMax Music API（唱歌）
        self.minimax_api_key = os.environ.get("MINIMAX_API_KEY", "")

    def is_available(self) -> bool:
        """检查语音服务是否可用"""
        return bool(self.asr_api_key and self.tts_api_key)

    # ========== ASR（异步 HTTP）==========

    async def transcribe(self, audio_url: str, audio_format: str = "ogg") -> str:
        """
        语音转文字（异步模式）。
        提交音频 URL → 轮询查询 → 返回识别文字。

        Args:
            audio_url: 音频文件公网可访问 URL
            audio_format: 音频格式（ogg/mp3/wav）

        Returns:
            识别的文字（可能为空字符串）
        """
        if not self.asr_api_key:
            print("🎤 [ASR] ❌ API Key 未配置")
            return ""

        request_id = str(uuid.uuid4())
        print(f"🎤 [ASR] 提交任务: request_id={request_id} format={audio_format}")

        try:
            # 1. 提交任务
            submit_payload = {
                "user": {"uid": "sundayos"},
                "audio": {
                    "url": audio_url,
                    "format": audio_format,
                    "codec": "raw" if audio_format in ("wav", "pcm") else audio_format,
                },
                "request": {
                    "model_name": "bigmodel",
                    "enable_itn": True,
                    "enable_punc": True,
                },
            }

            submit_headers = {
                "Content-Type": "application/json",
                "X-Api-Key": self.asr_api_key,
                "X-Api-Resource-Id": self.asr_resource_id,
                "X-Api-Request-Id": request_id,
                "X-Api-Sequence": "-1",
            }

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    DOUBAO_ASR_SUBMIT_URL,
                    headers=submit_headers,
                    json=submit_payload,
                )

            status_code = resp.headers.get("X-Api-Status-Code", "")
            if status_code != "20000000":
                message = resp.headers.get("X-Api-Message", "unknown")
                print(f"🎤 [ASR] ❌ 提交失败: code={status_code} msg={message}")
                # 尝试从 body 获取更多错误信息
                try:
                    err = resp.json()
                    print(f"🎤 [ASR] 错误详情: {json.dumps(err, ensure_ascii=False)[:300]}")
                except:
                    pass
                return ""

            print(f"🎤 [ASR] ✅ 任务已提交，开始轮询...")

            # 2. 轮询查询结果
            query_headers = {
                "Content-Type": "application/json",
                "X-Api-Key": self.asr_api_key,
                "X-Api-Resource-Id": self.asr_resource_id,
                "X-Api-Request-Id": request_id,
            }

            elapsed = 0
            while elapsed < ASR_MAX_WAIT:
                await asyncio.sleep(ASR_POLL_INTERVAL)
                elapsed += ASR_POLL_INTERVAL

                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        DOUBAO_ASR_QUERY_URL,
                        headers=query_headers,
                        json={},
                    )

                code = resp.headers.get("X-Api-Status-Code", "")

                if code == "20000000":
                    # 任务完成，获取结果
                    try:
                        result = resp.json()
                        text = result.get("result", {}).get("text", "")
                        print(f"🎤 [ASR] ✅ 识别完成（{elapsed}s）: '{text[:80]}'")
                        return text
                    except json.JSONDecodeError:
                        print(f"🎤 [ASR] ❌ 无法解析结果 JSON")
                        return ""
                elif code in ("20000001", "20000002"):
                    # 处理中 / 排队中
                    print(f"🎤 [ASR] ⏳ 处理中... ({elapsed}s)")
                    continue
                else:
                    message = resp.headers.get("X-Api-Message", "")
                    print(f"🎤 [ASR] ❌ 查询失败: code={code} msg={message}")
                    return ""

            print(f"🎤 [ASR] ⏰ 轮询超时（{ASR_MAX_WAIT}s）")
            return ""

        except Exception as e:
            print(f"🎤 [ASR] ❌ 异常: {type(e).__name__}: {e}")
            logger.error(f"ASR 异常: {e}")
            return ""

    # ========== TTS（流式 HTTP）==========

    async def synthesize(self, text: str, emotion: str = "default") -> bytes:
        """
        文字转语音，返回 MP3 音频数据。
        长文本自动分段合成后拼接。
        自动去掉括号里的动作描述（如"清了清嗓子"），避免被读出来。
        """
        import re
        # 清洗：去掉括号里的内容（动作描述、状态提示等）
        text = re.sub(r'[（(].*?[）)]', '', text)
        text = text.strip()

        context_text = EMOTION_PROMPTS.get(emotion, "")
        chunks = self.split_for_tts(text, max_chars=200)

        if len(chunks) == 1:
            return await self._synthesize_chunk(chunks[0], context_text)

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
            "X-Api-Key": self.tts_api_key,
            "X-Api-Resource-Id": self.tts_resource_id,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(DOUBAO_TTS_URL, headers=headers, json=payload)
            status = resp.status_code
            body = resp.text
            print(f"🎤 [TTS] HTTP {status}, body first 300 chars: {body[:300]}")

            if status != 200:
                raise RuntimeError(f"TTS HTTP {status}: {body[:300]}")
            resp.raise_for_status()

        audio_chunks = []
        for line in body.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue

            code = parsed.get("code")
            data_val = parsed.get("data")
            if code == 0 and data_val:
                audio_chunks.append(base64.b64decode(data_val))
            elif code == 20000000:
                break  # 流结束
            elif code is not None and code != 0:
                raise RuntimeError(
                    f"TTS error: code={code} msg={parsed.get('message', '')}"
                )

        if not audio_chunks:
            raise RuntimeError("TTS returned no audio data")

        return b"".join(audio_chunks)

    async def synthesize_singing(self, text: str) -> bytes:
        """
        唱歌模式：用甜美歌声合成歌词。
        自动清洗括号内容 + 逐句合成。
        """
        import re
        text = re.sub(r'[（(].*?[）)]', '', text)
        text = text.strip()
        context_text = EMOTION_PROMPTS.get("singing", "")
        chunks = self.split_for_tts(text, max_chars=200)
        audio_parts = []
        for chunk in chunks:
            audio = await self._synthesize_chunk(chunk, context_text)
            audio_parts.append(audio)
        return b"".join(audio_parts)

    # ========== MiniMax Music（真正的唱歌）==========

    async def generate_music(self, lyrics: str, style: str = "甜美可爱的女声，轻快J-Pop") -> bytes:
        """
        调用 MiniMax Music API 生成真正的歌曲（带旋律）。
        
        Args:
            lyrics: 歌词文本，用 \\n 分隔行
            style: 音乐风格描述
        
        Returns:
            MP3 音频 bytes
        """
        if not self.minimax_api_key:
            raise RuntimeError("MiniMax API Key 未配置")

        # 去掉括号里的动作描述
        import re
        lyrics = re.sub(r'[（(].*?[）)]', '', lyrics)
        lyrics = lyrics.strip()

        payload = {
            "model": "music-2.6-free",
            "prompt": style,
            "lyrics": lyrics,
            "audio_setting": {
                "sample_rate": 44100,
                "bitrate": 256000,
                "format": "mp3",
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.minimax_api_key}",
        }

        print(f"🎵 [MUSIC] 生成歌曲: style={style[:50]}... lyrics_len={len(lyrics)}")

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(MINIMAX_MUSIC_URL, headers=headers, json=payload)
            data = resp.json()

        status = data.get("base_resp", {}).get("status_code")
        msg = data.get("base_resp", {}).get("status_msg", "")

        if status != 0:
            raise RuntimeError(f"MiniMax Music 错误: code={status} msg={msg}")

        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise RuntimeError("MiniMax Music 未返回音频数据")

        duration = data.get("extra_info", {}).get("music_duration", 0)
        print(f"🎵 [MUSIC] ✅ 生成成功！时长={duration}ms")

        return bytes.fromhex(audio_hex)

    # ========== MiniMax Cover（翻唱：保留原曲旋律）==========

    async def preprocess_cover(self, audio_url: str) -> dict:
        """
        第一步：预处理原曲，提取音频特征和结构化歌词（免费）。

        Args:
            audio_url: 原曲的公开可访问 URL

        Returns:
            {"cover_feature_id": "...", "formatted_lyrics": "...", "audio_duration": 123}
        """
        if not self.minimax_api_key:
            raise RuntimeError("MiniMax API Key 未配置")

        payload = {
            "model": "music-cover-free",
            "audio_url": audio_url,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.minimax_api_key}",
        }

        print(f"🎵 [COVER-PRE] 预处理原曲: {audio_url[:80]}...")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(MINIMAX_COVER_PREPROCESS_URL, headers=headers, json=payload)
            data = resp.json()

        status = data.get("base_resp", {}).get("status_code")
        msg = data.get("base_resp", {}).get("status_msg", "")

        if status != 0:
            raise RuntimeError(f"Cover 预处理失败: code={status} msg={msg}")

        feature_id = data.get("cover_feature_id", "")
        lyrics = data.get("formatted_lyrics", "")
        duration = data.get("audio_duration", 0)

        if not feature_id:
            raise RuntimeError("Cover 预处理未返回 feature_id")

        print(f"🎵 [COVER-PRE] ✅ feature_id={feature_id[:20]}... duration={duration}s lyrics_len={len(lyrics)}")

        return {
            "cover_feature_id": feature_id,
            "formatted_lyrics": lyrics,
            "audio_duration": duration,
        }

    async def generate_cover(
        self,
        cover_feature_id: str,
        lyrics: str = "",
        prompt: str = "甜美可爱的女声，J-Pop动漫主题曲风格，温柔甜美",
    ) -> bytes:
        """
        第二步：用预处理特征 + 歌词 + 风格生成翻唱（保留原曲旋律）。

        Args:
            cover_feature_id: 预处理返回的特征 ID
            lyrics: 要唱的歌词（可选，不传则自动从原曲提取）
            prompt: 翻唱风格描述

        Returns:
            MP3 音频 bytes
        """
        if not self.minimax_api_key:
            raise RuntimeError("MiniMax API Key 未配置")

        payload = {
            "model": "music-cover-free",
            "cover_feature_id": cover_feature_id,
            "prompt": prompt,
            "audio_setting": {
                "sample_rate": 44100,
                "bitrate": 256000,
                "format": "mp3",
            },
        }

        # 如果传了歌词，加入 payload
        if lyrics:
            import re
            lyrics = re.sub(r'[（(].*?[）)]', '', lyrics)
            lyrics = lyrics.strip()
            payload["lyrics"] = lyrics

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.minimax_api_key}",
        }

        print(f"🎵 [COVER] 生成翻唱: feature_id={cover_feature_id[:20]}... lyrics_len={len(lyrics)}")

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(MINIMAX_MUSIC_URL, headers=headers, json=payload)
            data = resp.json()

        status = data.get("base_resp", {}).get("status_code")
        msg = data.get("base_resp", {}).get("status_msg", "")

        if status != 0:
            raise RuntimeError(f"Cover 生成失败: code={status} msg={msg}")

        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise RuntimeError("Cover 未返回音频数据")

        duration = data.get("extra_info", {}).get("music_duration", 0)
        print(f"🎵 [COVER] ✅ 翻唱成功！时长={duration}ms")

        return bytes.fromhex(audio_hex)

    @staticmethod
    def split_for_tts(text: str, max_chars: int = 300) -> list[str]:
        """
        按句号/感叹号/问号分段，保证每段不超过 max_chars。
        若单句本身超过 max_chars，再做硬切兜底。
        """
        import re
        sentences = re.split(r'(?<=[。！？\n])\s*', text)
        chunks = []
        current = ""
        for s in sentences:
            s = s.strip()
            if not s:
                continue
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
    "singing": "用甜美柔和的歌声，像在轻轻哼唱，旋律优美温柔，像睡前摇篮曲一样，慢慢地唱，每个字都带着旋律和节奏",
    "default": "用自然甜美的声音，像和朋友聊天一样，语调温柔上扬",
}


# 全局单例
voice_service = VoiceService()
