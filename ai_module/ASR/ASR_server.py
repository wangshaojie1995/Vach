import asyncio
import websockets
import argparse
import json
from funasr import AutoModel
import os

# python -u ASR_server.py --host "0.0.0.0" --port 10197

# 设置日志级别
import logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.CRITICAL)

# 解析命令行参数
parser = argparse.ArgumentParser()
parser.add_argument("--host", type=str, default="0.0.0.0", help="host ip, localhost, 0.0.0.0")
parser.add_argument("--port", type=int, default=10197, help="grpc server port")
parser.add_argument("--ngpu", type=int, default=1, help="0 for cpu, 1 for gpu")
args = parser.parse_args()

# 初始化模型
print("model loading")
asr_model = AutoModel(model="paraformer-zh", model_revision="v2.0.4",
                      vad_model="fsmn-vad", vad_model_revision="v2.0.4",
                      punc_model="ct-punc-c", punc_model_revision="v2.0.4")
print("model loaded")
websocket_users = {}
task_queue = asyncio.Queue()

async def ws_serve(websocket, path):
    global websocket_users
    user_id = id(websocket)
    websocket_users[user_id] = websocket
    try:
        async for message in websocket:
            if isinstance(message, str):
                data = json.loads(message)
                if 'url' in data:
                    await task_queue.put((websocket, data['url']))
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"Connection closed: {e.reason}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
    finally:
        logger.info(f"Cleaning up connection for user {user_id}")
        if user_id in websocket_users:
            del websocket_users[user_id]
        await websocket.close()
        logger.info("WebSocket closed")

async def worker():
    while True:
        websocket, url = await task_queue.get()
        if websocket.open:
            await process_wav_file(websocket, url)
        else:
            logger.info("WebSocket connection is already closed when trying to process file")
        task_queue.task_done()

async def process_wav_file(websocket, url):
    wav_path = url
    try:
        res = asr_model.generate(input=wav_path)
        if res:
            if 'text' in res[0] and websocket.open:
                await websocket.send(res[0]['text'])
    except Exception as e:
        print(f"Error during model.generate: {e}")
    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)

async def main():
    start_server = websockets.serve(ws_serve, args.host, args.port, subprotocols=["binary"], ping_interval=10)
    await start_server
    worker_task = asyncio.create_task(worker())
    await worker_task

# 使用 asyncio 运行主函数
asyncio.run(main())