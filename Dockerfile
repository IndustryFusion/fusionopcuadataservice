FROM python:3.15
COPY requirements.txt /
RUN pip install -r requirements.txt

COPY . /
WORKDIR /src

CMD [ "python3", "-u", "main.py" ]