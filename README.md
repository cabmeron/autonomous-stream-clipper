# Autonomous Stream Clipper

ASC is a 100% local pipeline that captures viral stream moments in real time. 

It monitors Twitch Chat velocity, audio volume surges, and on-screen OCR win multipliers to extract candidate clips. 

Everything runs on your machine with zero external cloud dependencies or API keys required.

The app continuously records a rolling video buffer in memory and captures post-event reactions when excitement spikes. 

It optimizes boundaries around natural speech pauses and renders high-retention 9:16 vertical clips with burned-in subtitles. 

All media and metadata are saved locally to an embedded SQLite database and local disk storage.

## Installation

Clone the repository and set up a Python virtual environment. Install all required dependencies using `pip install -r requirements.txt`. Ensure FFmpeg is installed on your system.

```bash
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
```

## Running the App

Start the application by running `orchestrator.py`. Open your web browser and navigate to `http://localhost:8000`. The server starts in an idle standby state awaiting your input.

```bash
./venv/bin/python orchestrator.py
```

## Web UI Usage

Enter any Twitch channel name into the top bar and click Connect to start live monitoring. Watch the real-time sparkline telemetry graph update at 10 Hz as chat and audio signals arrive. Preview rendered 9:16 vertical clips in the bottom triage gallery and approve them with one click.

## Running Tests

Run the automated test suite with `./venv/bin/pytest tests/ -v`. The test suite verifies velocity math, audio decibel spikes, OCR extraction, local boundaries, and 9:16 video rendering.

```bash
./venv/bin/pytest tests/ -v
```
