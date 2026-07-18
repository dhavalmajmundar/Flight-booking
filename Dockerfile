FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY flight_bot ./flight_bot

RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 botuser
USER botuser

CMD ["python", "-m", "flight_bot.main"]

