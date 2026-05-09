import asyncio
import aiohttp
import cv2
import numpy as np
import time
import rerun as rr
import rerun.blueprint as rrb
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
import threading
import argparse

stop_event = threading.Event()
frame_count = 0

async def receive_whep_stream(whep_url, device_id=0):
    global frame_count

    # Initialize Rerun
    rr.init("WHEP Stream Visualization")

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

                    # Save the frame to video file
                    video_writer.write(img)
                    
                    # Log frames to Rerun
                    rr.set_time("frame_nr", sequence=frame_count)
                    
                    # Log the original image
                    rr.log("image/rgb", rr.Image(img, color_model="BGR"))
                    
                    # Convert to grayscale
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    rr.log("image/gray", rr.Image(gray))
                    
                    # Run the canny edge detector
                    canny = cv2.Canny(gray, 50, 200)
                    rr.log("image/canny", rr.Image(canny))
                    
                    # Optional: Add more image processing visualizations here
                    
                    frame_count += 1

                    # Display count every 5 seconds
                    now = time.time()
                    if now - last_report_time >= 5:
                        new_images = frame_count - old_count
                        fps = new_images/5
                        print(f"🧮 Frames saved: {frame_count}")
                        print(f"🧮 FPS: {fps}")
                        
                        
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
            await asyncio.sleep(1)
    finally:
        print("🛑 Closing peer connection")
        await pc.close()

def main():
    parser = argparse.ArgumentParser(description="WHEP client with Rerun visualization")
    parser.add_argument(
        "--url2", 
        type=str, 
        default="http://10.42.0.99:8889/cam/whep",
        help="WHEP endpoint URL"
    )
    parser.add_argument("--device", type=int, default=0, help="Device ID (for fallback)")
    rr.script_add_args(parser)
    args = parser.parse_args()
    
    # Setup rerun with a nice layout
    rr.script_setup(
        args,
        "whep_stream_visualization",
        default_blueprint=rrb.Vertical(
            rrb.Horizontal(
                rrb.Spatial2DView(origin="/image/rgb", name="Original Stream"),
                rrb.Spatial2DView(origin="/image/gray", name="Grayscale"),
            ),
            rrb.Horizontal(
                rrb.Spatial2DView(origin="/image/canny", name="Edge Detection")
            ),
            row_shares=[1, 1],
        ),
    )
    
    print("🚀 Starting WHEP client with Rerun visualization")
    try:
        asyncio.run(receive_whep_stream(args.url2, args.device))
    except KeyboardInterrupt:
        print("\n🛑 Received interrupt signal")
    except Exception as e:
        print(f"🔥 Main error: {e}")
    finally:
        stop_event.set()
        print(f"👋 Application stopped — Total frames saved: {frame_count}")
        rr.script_teardown(args)

if __name__ == "__main__":
    main()
