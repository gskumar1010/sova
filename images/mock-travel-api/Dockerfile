# images/mock-travel-api/Dockerfile
FROM python:3.11-slim

WORKDIR /svc
COPY app/mock_travel_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/__init__.py /svc/app/__init__.py
COPY app/mock_travel_api /svc/app/mock_travel_api

EXPOSE 8080
CMD ["uvicorn", "app.mock_travel_api.main:app", "--host", "0.0.0.0", "--port", "8080"]
