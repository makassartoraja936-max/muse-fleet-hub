FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and payloads
COPY . .

# Railway automatically injects $PORT environment variable
ENV PORT=9000
EXPOSE 9000

CMD ["python", "-u", "hub_server.py"]
