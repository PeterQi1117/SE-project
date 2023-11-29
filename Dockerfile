FROM python:3.9

COPY requirements.txt /
RUN pip3 install -r requirements.txt

COPY . /app

EXPOSE 8080
ENV PORT 8080

WORKDIR /app

CMD ["gunicorn", "app:app", "--timeout 0", "--bind", "0.0.0.0:8080"]