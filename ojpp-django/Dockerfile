FROM python:3.12-slim

WORKDIR /usr/src/app
EXPOSE ${PORT:-80}

RUN apt-get update && apt-get install -y gdal-bin gdal-data

ENV ENVIRONMENT=docker-production

# PIP_NO_CACHE_DIR=off mean NO CACHING. This is stupid, but it's the way it is. See https://github.com/pypa/pip/issues/2897#issuecomment-115319916
RUN PIP_NO_CACHE_DIR=off pip install pipenv==2023.12.1 gunicorn

COPY Pipfile Pipfile.lock ./

RUN PIP_NO_CACHE_DIR=off pipenv install --system --deploy

COPY . .

CMD ["./docker-entrypoint.sh"]
