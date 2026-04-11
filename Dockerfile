FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot files
COPY bot.py .
COPY Procfile .
COPY runtime.txt .

# Run bot
CMD ["python", "bot.py"]
