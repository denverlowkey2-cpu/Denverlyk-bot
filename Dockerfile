FROM python:3.11-slim

WORKDIR /app

# Install system deps for matplotlib charts + gTTS voice
RUN apt-get update && apt-get install -y \
    fonts-dejavu \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
