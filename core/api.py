import asyncio
import json
import random

import names

from datetime import datetime, timezone
from typing import Literal, Any
from curl_cffi.requests import AsyncSession, Response

from models import Account
from .exceptions.base import APIError, SessionRateLimited, ServerError
from loader import config, headers_manager as HeadersManager




class APIClient:
    def __init__(self, base_url: str, account: Account):
        self.user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        self.base_url = base_url
        self.account_data = account
        self.session = self._create_session()

    def _create_session(self) -> AsyncSession:
        session = AsyncSession(impersonate="chrome124", verify=False)
        session.timeout = 30
        session.headers = HeadersManager.get_base_headers()

        if self.account_data.proxy:
            session.proxies = {
                "http": self.account_data.proxy.as_url,
                "https": self.account_data.proxy.as_url,
            }

        return session


    async def clear_request(self, url: str) -> Response:
        session = self._create_session()
        return await session.get(url, allow_redirects=True, verify=False)

    @staticmethod
    async def _verify_response(response_data: dict | list):
        if isinstance(response_data, dict):
            if "status" in str(response_data):
                if isinstance(response_data, dict):
                    if response_data.get("status") is False:
                        raise APIError(
                            f"API returned an error: {response_data}", response_data
                        )

            elif "success" in str(response_data):
                if isinstance(response_data, dict):
                    if response_data.get("success") is False:
                        raise APIError(
                            f"API returned an error: {response_data}", response_data
                        )

    async def send_request(
        self,
        request_type: Literal["POST", "GET", "OPTIONS"] = "POST",
        method: str = None,
        json_data: dict = None,
        params: dict = None,
        url: str = None,
        headers: dict = None,
        cookies: dict = None,
        verify: bool = True,
        max_retries: int = 3,
        retry_delay: float = 3.0,
    ):
        url = url if url else f"{self.base_url}{method}"

        for attempt in range(max_retries):
            try:
                if request_type == "POST":
                    response = await self.session.post(
                        url,
                        json=json_data,
                        params=params,
                        headers=headers if headers else self.session.headers,
                        cookies=cookies,
                    )
                elif request_type == "OPTIONS":
                    response = await self.session.options(
                        url,
                        headers=headers if headers else self.session.headers,
                        cookies=cookies,
                    )
                else:
                    response = await self.session.get(
                        url,
                        params=params,
                        headers=headers if headers else self.session.headers,
                        cookies=cookies,
                    )

                if verify:
                    if response.status_code == 403:
                        raise SessionRateLimited("Session is rate limited")

                    if response.status_code in (500, 502, 503, 504):
                        raise ServerError(f"Server error - {response.status_code}")

                    try:
                        response_json = response.json()
                        await self._verify_response(response_json)
                        return response_json
                    except json.JSONDecodeError:
                        return response.text

                return response.text

            except ServerError as error:
                if attempt == max_retries - 1:
                    raise error
                await asyncio.sleep(retry_delay)

            except (APIError, SessionRateLimited):
                raise

            except Exception as error:
                if attempt == max_retries - 1:
                    raise ServerError(
                        f"Failed to send request after {max_retries} attempts: {error}"
                    )
                await asyncio.sleep(retry_delay)

        raise ServerError(f"Failed to send request after {max_retries} attempts")


class DawnExtensionAPI(APIClient):
    def __init__(self, account: Account):
        super().__init__("https://www.aeropres.in/chromeapi/dawn", account)
        self.wallet_data: dict[str, Any] = {}

    async def get_puzzle_id(self) -> str:
        response = await self.send_request(
            method="/v1/puzzle/get-puzzle",
            request_type="GET",
            params={"appid": self.account_data.appid},
        )
        return response["puzzle_id"]

    async def get_puzzle_image(self, puzzle_id: str) -> str:
        response = await self.send_request(
            method="/v1/puzzle/get-puzzle-image",
            request_type="GET",
            params={"puzzle_id": puzzle_id, "appid": self.account_data.appid},
        )

        return response.get("imgBase64")

    async def register(self, puzzle_id: str, answer: str) -> dict:
        headers = HeadersManager.get_base_headers()
        headers["content-type"] = "application/json"

        json_data = {
            "firstname": names.get_first_name(),
            "lastname": names.get_last_name(),
            "email": self.account_data.email,
            "mobile": "",
            "password": self.account_data.password,
            "country": "+91",
            "referralCode": random.choice(config.referral_codes) if config.referral_codes else "",
            "puzzle_id": puzzle_id,
            "ans": answer,
            'ismarketing': True,
            'browserName': 'Chrome',
        }

        return await self.send_request(
            method="/v1/puzzle/validate-register",
            json_data=json_data,
            params={"appid": self.account_data.appid},
            headers=headers,
        )

    async def keepalive(self) -> dict | str:
        headers = HeadersManager.get_base_headers()
        headers.update({
            "authorization": f"Bearer {HeadersManager.BEARER_TOKEN}",
            "content-type": "application/json",
        })

        json_data = {
            "username": self.account_data.email,
            "extensionid": "fpdkjdnhkakefebpekbdhillbhonfjjp",
            "numberoftabs": 0,
            "_v": "1.1.2",
        }

        return await self.send_request(
            method="/v1/userreward/keepalive",
            json_data=json_data,
            verify=False,
            headers=headers,
            params={"appid": self.account_data.appid},
        )

    async def user_info(self) -> dict:
        headers = HeadersManager.get_base_headers()
        headers.update({
            "authorization": f"Berear {HeadersManager.BEARER_TOKEN}",
            "content-type": "application/json",
        })

        response = await self.send_request(
            url="https://www.aeropres.in/api/atom/v1/userreferral/getpoint",
            request_type="GET",
            headers=headers,
            params={"appid": self.account_data.appid},
        )

        return response["data"]

    async def verify_registration(self, key: str, cloudflare_token: str):
        headers = HeadersManager.get_base_headers()
        headers.update({
            "content-type": "application/json",
            "origin": "https://www.aeropres.in",
        })

        return await self.send_request(
            method="/v1/userverify/verifycheck",
            json_data={"token": cloudflare_token},
            headers=headers,
            params={"key": key},
        )

    async def resend_verify_link(self, puzzle_id: str, answer: str) -> dict:
        headers = HeadersManager.get_base_headers()
        headers["content-type"] = "application/json"

        json_data = {
            'username': self.account_data.email,
            'puzzle_id': puzzle_id,
            'ans': answer,
        }

        return await self.send_request(
            method="/v1/user/resendverifylink/v2",
            json_data=json_data,
            params={"appid": self.account_data.appid},
            headers=headers,
        )

    async def complete_tasks(self, tasks: list[str] = None, delay: int = 1) -> None:
        if not tasks:
            tasks = ["telegramid", "discordid", "twitter_x_id"]

        headers = HeadersManager.get_base_headers()
        headers.update({
            "authorization": f"Bearer {HeadersManager.BEARER_TOKEN}",
            "content-type": "application/json",
        })

        for task in tasks:
            await self.send_request(
                method="/v1/profile/update",
                json_data={task: task},
                headers=headers,
                params={"appid": self.account_data.appid},
            )

            await asyncio.sleep(delay)

    async def verify_session(self) -> tuple[bool, str]:
        try:
            await self.user_info()
            return True, "Session is valid"

        except ServerError:
            return True, "Server error"

        except APIError as error:
            return False, str(error)

    async def login(self, puzzle_id: str, answer: str):
        headers = HeadersManager.get_base_headers()
        headers["content-type"] = "application/json"

        current_time = datetime.now(timezone.utc)
        formatted_datetime_str = (
            current_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        )

        json_data = {
            "username": self.account_data.email,
            "password": self.account_data.password,
            "logindata": {
                '_v': {
                    'version': '1.1.2',
                },
                'datetime': formatted_datetime_str,
            },
            "puzzle_id": puzzle_id,
            "ans": answer,
        }

        response = await self.send_request(
            method="/v1/user/login/v2",
            json_data=json_data,
            params={"appid": self.account_data.appid},
            headers=headers,
        )

        bearer = response.get("data", {}).get("token")
        if bearer:
            HeadersManager.BEARER_TOKEN = bearer.replace("Bearer ", "")
        else:
            raise APIError(f"Failed to login: {response}")
