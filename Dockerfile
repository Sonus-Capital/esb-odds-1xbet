FROM apify/actor-python:3.12

COPY requirements.txt .
RUN pip install -r requirements.txt
RUN python -m playwright install chromium --with-deps

COPY . .

CMD ["python", "-m", "src.main"]
