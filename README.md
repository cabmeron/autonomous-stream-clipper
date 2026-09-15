# Autonomous Stream Clipper

ASC is a 100% local pipeline that captures viral stream moments in real time. 

It monitors Twitch Chat velocity, audio volume surges, and on-screen OCR win multipliers across multiple live channels simultaneously. 

Everything runs on your machine with zero external cloud dependencies or API keys required.

The app maintains rolling in-memory video buffers and captures post-event reactions when excitement spikes. 

It optimizes boundaries around natural speech pauses and renders full-sized uncropped clips in original resolution. 

All media and metadata are saved locally to an embedded SQLite database and local disk storage.

<img width="1153" height="847" alt="Screenshot 2026-09-03 at 12 33 55 PM" src="https://github.com/user-attachments/assets/d9cea51c-dfd0-4c42-bf4e-cb0418c4da89" />

## Installation

Clone the repository and set up a Python virtual environment. Install all required dependencies using pip install -r requirements.txt. Ensure FFmpeg is installed on your system.

```bash
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Running the App

Start the application by running orchestrator.py. Open your web browser and navigate to http://localhost:8000. The server starts in an idle standby state awaiting your input.

```bash
./venv/bin/python orchestrator.py
```

## Multi-Session Web UI Usage

Add any number of Twitch channels using the top bar to create concurrent stream sessions. Switch between tabs to view the live Twitch stream, real-time velocity metrics, and audio levels for each channel. Each stream has its own dedicated clips section where you can preview and delete clips.

## Running Tests

Run the automated test suite with ./venv/bin/pytest tests/ -v. The test suite verifies multi-session lifecycles, velocity math, audio spikes, OCR extraction, and full-sized video rendering.

```bash
./venv/bin/pytest tests/ -v
```
