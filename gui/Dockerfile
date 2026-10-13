FROM python:3.13-slim
WORKDIR /opt/gui
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps --no-build-isolation . && useradd --uid 10001 --create-home gui
USER 10001
ENV MOSAIC_GUI_HOST=0.0.0.0
ENV MOSAIC_GUI_PORT=8050
EXPOSE 8050
CMD ["mosaic-gui"]
