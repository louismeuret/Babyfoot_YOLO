import cv2
import numpy as np
import time
import threading
import os
import datetime
import dearpygui.dearpygui as dpg
from collections import deque
import asyncio
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.signaling import TcpSocketSignaling
from aiortc.mediastreams import MediaStreamTrack

# Replace with your WebRTC setup
SIGNALING_SERVER = "10.42.0.99"
SIGNALING_PORT = 8889

# Variables
trajectory_points = deque(maxlen=50)
prev_ball_position = None
smoothing_enabled = True
recording = False
video_writer = None
recording_status = "Not Recording"
current_frame = None

# Kalman Filter setup
kalman = cv2.KalmanFilter(4, 2)
kalman.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
kalman.transitionMatrix = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], np.float32)
kalman.processNoiseCov = np.eye(4, dtype=np.float32) * 0.03

# FPS Tracking
frame_count = 0
start_time = time.time()

# Function to toggle smoothing
def toggle_smoothing():
    global smoothing_enabled
    smoothing_enabled = not smoothing_enabled

# Function to start/stop recording
def start_stop_recording():
    global recording, video_writer, recording_status

    if recording:
        if video_writer:
            video_writer.release()
            video_writer = None
        recording = False
        recording_status = "Not Recording"
    else:
        # Ensure a unique filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recording_{timestamp}.avi"
        
        fourcc = cv2.VideoWriter_fourcc(*"XVID")
        video_writer = cv2.VideoWriter(filename, fourcc, 20.0, (640, 480))
        recording = True
        recording_status = f"Recording: {filename}"

    dpg.set_value("recording_status_text", recording_status)

# Class to handle video frames from WebRTC
class VideoFrameProcessor:
    def __init__(self):
        self.frame = None
        self.new_frame_available = threading.Event()
    
    def process_frame(self, frame):
        self.frame = frame
        self.new_frame_available.set()
        
    def get_frame(self):
        self.new_frame_available.wait()
        self.new_frame_available.clear()
        return self.frame

# Custom video track receiver
class VideoTrackReceiver(MediaStreamTrack):
    kind = "video"
    
    def __init__(self, track, processor):
        super().__init__()
        self.track = track
        self.processor = processor
        
    async def recv(self):
        frame = await self.track.recv()
        if self.processor:
            self.processor.process_frame(frame)
        return frame

# WebRTC connection setup
async def connect_to_webrtc():
    global video_processor
    
    # Create signaling and peer connection
    signaling = TcpSocketSignaling(SIGNALING_SERVER, SIGNALING_PORT)
    pc = RTCPeerConnection()
    
    # Set up handlers
    @pc.on("track")
    def on_track(track):
        print(f"Received {track.kind} track")
        if track.kind == "video":
            video_processor = VideoFrameProcessor()
            pc.addTrack(VideoTrackReceiver(track, video_processor))
    
    # Connect to signaling server
    await signaling.connect()
    
    # Create and send offer
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    await signaling.send(pc.localDescription)
    
    # Wait for answer
    obj = await signaling.receive()
    if isinstance(obj, RTCSessionDescription):
        await pc.setRemoteDescription(obj)
    
    return pc

# UI setup with DearPyGui
dpg.create_context()
dpg.create_viewport(title='Foosball Tracker', width=400, height=200)

with dpg.window(label="Controls", width=400, height=150):
    dpg.add_button(label="Toggle Smoothing", callback=toggle_smoothing)
    dpg.add_button(label="Start/Stop Recording", callback=start_stop_recording)
    dpg.add_text("FPS: 0", tag="fps_text")
    dpg.add_text("Not Recording", tag="recording_status_text")

dpg.setup_dearpygui()
dpg.show_viewport()

# Function to process video frames
def process_video():
    global prev_ball_position, recording, video_writer, frame_count, start_time, current_frame
    
    while True:
        if hasattr(video_processor, 'get_frame'):
            frame = video_processor.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue
                
            # Convert frame to numpy array
            current_frame = frame.to_ndarray(format="bgr24")
            
            # Process frame
            process_current_frame()
            
            # Display updated frame
            cv2.imshow("Foosball Tracking", current_frame)
            
            if recording and video_writer:
                video_writer.write(current_frame)
                
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        else:
            time.sleep(0.1)  # Wait for video_processor to be ready
            
    cv2.destroyAllWindows()

# Process the current frame with ball detection and tracking
def process_current_frame():
    global prev_ball_position, frame_count, start_time, current_frame, trajectory_points
    
    if current_frame is None:
        return
        
    # Compute FPS
    frame_count += 1
    elapsed_time = time.time() - start_time
    if elapsed_time > 1.0:
        fps = frame_count / elapsed_time
        dpg.set_value("fps_text", f"FPS: {fps:.2f}")
        frame_count = 0
        start_time = time.time()

    # Process frame (detect ball, update Kalman, etc.)
    gray = cv2.cvtColor(current_frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, 1.2, 30, 
                              param1=50, param2=30, minRadius=5, maxRadius=30)

    # Initialize default position
    cx, cy = 0, 0
    
    if circles is not None:
        circles = np.uint16(np.around(circles))
        cx, cy, r = circles[0][0]
        prev_ball_position = (cx, cy)
        measurement = np.array([[np.float32(cx)], [np.float32(cy)]])
        kalman.correct(measurement)
    else:
        predicted = kalman.predict()
        cx, cy = int(predicted[0]), int(predicted[1])

    trajectory_points.append((cx, cy))

    # Draw trajectory
    for i in range(1, len(trajectory_points)):
        cv2.line(current_frame, trajectory_points[i - 1], trajectory_points[i], (0, 255, 0), 2)

    cv2.circle(current_frame, (cx, cy), 10, (255, 0, 0), -1)

# Initialize variables
video_processor = None

# Start the event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Start WebRTC connection in background
connection_task = loop.create_task(connect_to_webrtc())

# Start the video processing thread
video_thread = threading.Thread(target=process_video, daemon=True)
video_thread.start()

# Start the DearPyGui main loop
dpg.start_dearpygui()

# Cleanup
dpg.destroy_context()
loop.close()
cv2.destroyAllWindows()
