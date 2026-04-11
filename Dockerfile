FROM python:3.11-slim

WORKDIR /app

# কপি করার আগে ফাইল আছে কিনা চেক করুন
COPY requirements.txt .

# যদি requirements.txt না থাকে, তাহলে তৈরি করুন
RUN if [ ! -f requirements.txt ]; then \
        echo "python-telegram-bot==20.7" > requirements.txt && \
        echo "pyotp==2.9.0" >> requirements.txt && \
        echo "requests==2.31.0" >> requirements.txt; \
    fi

# প্যাকেজ ইনস্টল করুন
RUN pip install --no-cache-dir -r requirements.txt

# বট ফাইল কপি করুন
COPY bot.py .

# রান করুন
CMD ["python", "bot.py"]