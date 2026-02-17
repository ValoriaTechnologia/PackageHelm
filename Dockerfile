FROM python:3.12-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /requirements.txt
RUN pip install -r /requirements.txt
COPY entrypoint.py /entrypoint.py

ENTRYPOINT ["python", "/entrypoint.py"]

