import asyncio
import aiohttp
import cv2
import numpy as np
import time
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
import threading
import queue


stop_event = threading.Event()
frame_count = 0
frame_queue = queue.Queue(maxsize=30)  # Limit queue size to prevent memory issues

def process_frames_from_queue():
    """Process frames from the queue and display them"""
    if frame_queue.empty():
        return
    
    # Get the latest frame
    frame = frame_queue.get()
    cv2.imshow("Live Stream", frame)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q'):
        stop_event.set()


async def receive_whep_stream(whep_url):
    global frame_count

    config = RTCConfiguration(iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")])
    pc = RTCPeerConnection(configuration=config)

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print(f"❄️ ICE Connection State: {pc.iceConnectionState}")
        if pc.iceConnectionState == "failed":
            await pc.close()
            stop_event.set()

    video = pc.addTransceiver("video", direction="recvonly")

    # Initialize video writer later once we get the first frame
    video_writer = None

    @pc.on("track")
    async def on_track(track):
        nonlocal video_writer
        print(f"🎬 Track received: {track.kind} (id: {track.id})")

        last_report_time = time.time()
        frame_count = 0
        old_count = 0
        while not stop_event.is_set():
            try:
                frame = await track.recv()
                if hasattr(frame, 'to_ndarray'):
                    img = frame.to_ndarray(format="bgr24")
                    if img is None:
                        continue

                    if video_writer is None:
                        h, w = img.shape[:2]
                        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                        video_writer = cv2.VideoWriter('output.mp4', fourcc, 25.0, (w, h))
                        print(f"📹 Initialized VideoWriter with resolution: {w}x{h}")
                    
                    # Don't block if queue is full
                    try:
                        frame_queue.put_nowait(img.copy())
                    except queue.Full:
                        # Drop frame if queue is full
                        pass
                        
                    video_writer.write(img)
                    frame_count += 1

                    # Display count every 5 seconds
                    now = time.time()
                    if now - last_report_time >= 5:
                        new_images = frame_count - old_count
                        print(f"🧮 Frames saved: {frame_count}")
                        print(f"🧮 FPS: {new_images/5}")
                        last_report_time = now
                        old_count = frame_count

            except Exception as e:
                print(f"🔥 Track error: {str(e)}")
                break

        if video_writer:
            video_writer.release()
            print("💾 VideoWriter released")

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    print("📤 Local Description Set - Gathering ICE Candidates")
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            whep_url,
            data=pc.localDescription.sdp,
            headers={"Content-Type": "application/sdp"}
        ) as resp:
            if resp.status not in (200, 201):
                error = await resp.text()
                print(f"🚨 WHEP Error {resp.status}: {error}")
                stop_event.set()
                return

            answer_sdp = await resp.text()
            print("📥 Received SDP Answer")

    try:
        await pc.setRemoteDescription(RTCSessionDescription(
            sdp=answer_sdp,
            type="answer"
        ))
        print("✅ Remote Description Set")
    except Exception as e:
        print(f"🚨 Error setting remote description: {e}")
        stop_event.set()
        return

    try:
        while not stop_event.is_set():
            await asyncio.sleep(0.1)
    finally:
        print("🛑 Closing peer connection")
        await pc.close()


async def main_async():
    print("🚀 Starting WHEP client (record + display)")
    
    # Create a display task that runs alongside the stream receiver
    display_task = asyncio.create_task(run_display_loop())
    
    # Run the main streaming task
    stream_task = asyncio.create_task(receive_whep_stream("http://10.42.0.99:8889/cam/whep"))
    
    # Wait for either task to complete
    await asyncio.wait([stream_task, display_task], return_when=asyncio.FIRST_COMPLETED)
    
    # Once one completes, set the stop event
    stop_event.set()
    
    # Wait for remaining tasks to complete
    await asyncio.gather(stream_task, display_task, return_exceptions=True)
    
    print(f"👋 Application stopped — Total frames saved: {frame_count}")


async def run_display_loop():
    """Async function to update CV2 display while allowing asyncio to run"""
    cv2.namedWindow("Live Stream")
    
    while not stop_event.is_set():
        process_frames_from_queue()
        # Short sleep to yield to other tasks
        await asyncio.sleep(0.01)
    
    cv2.destroyAllWindows()


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n🛑 Received interrupt signal")
        stop_event.set()
    except Exception as e:
        print(f"🔥 Main error: {e}")
        stop_event.set()


if __name__ == "__main__":
    main()