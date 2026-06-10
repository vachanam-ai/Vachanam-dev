"""Trigger an outbound call: explicitly dispatch the agent into a fresh room.

Usage:
    python make_call.py --to +916303620981

Official pattern: https://docs.livekit.io/agents/start/telephony/#outbound
"""
import argparse
import asyncio
import json
import time

from dotenv import load_dotenv
from livekit import api

load_dotenv(".env")

AGENT_NAME = "vachanam-agent"


async def main(phone: str) -> None:
    lkapi = api.LiveKitAPI()
    room_name = f"outbound-{phone.lstrip('+')}-{int(time.time())}"

    dispatch = await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=AGENT_NAME,
            room=room_name,
            metadata=json.dumps({"phone_number": phone}),
        )
    )
    print(f"Dispatch created: {dispatch.id}")
    print(f"Room: {room_name}")
    print("Agent will now dial the number. Watch the agent terminal for progress.")

    await lkapi.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", required=True, help="Phone number in E.164, e.g. +91...")
    args = parser.parse_args()
    asyncio.run(main(args.to))
