"""
utils/dishost_api.py
디스호스트 봇 리스트 API 연동
"""

import aiohttp
import logging
from config import DISHOST_API_KEY, DISHOST_API_URL

logger = logging.getLogger(__name__)


async def post_server_count(server_count: int) -> dict | None:
    """봇 서버 수를 디스호스트에 POST"""
    url = f"{DISHOST_API_URL}/bots/stats"
    headers = {
        "X-API-Key": DISHOST_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {"server_count": server_count}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if resp.status in (200,201):
                    logger.info(f"[디스호스트] 서버 수 업데이트 성공: {server_count}개")
                else:
                    logger.warning(f"[디스호스트] 서버 수 업데이트 실패 ({resp.status}): {data}")
                return data
    except Exception as e:
        logger.error(f"[디스호스트] API 요청 오류: {e}")
        return None


async def check_user_vote(user_id: int) -> dict | None:
    url = f"{DISHOST_API_URL}/bots/check-vote"
    headers = {"X-API-Key": DISHOST_API_KEY}
    params = {"user_id": str(user_id)}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as resp:

                text = await resp.text()
                logger.info(f"[디스호스트 RAW 응답] status={resp.status}, body={text}")

                try:
                    data = await resp.json()
                except Exception:
                    logger.error("[디스호스트] JSON 변환 실패")
                    return None

                if resp.status != 200:
                    logger.error(f"[디스호스트] 실패 응답: {data}")
                    return None

                return data

    except Exception as e:
        logger.error(f"[디스호스트] API 요청 오류: {e}")
        return None