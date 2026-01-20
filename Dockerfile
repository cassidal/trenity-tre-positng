# Используем легкий образ Python
FROM python:3.11-slim

# Устанавливаем системные зависимости
# ffmpeg - для работы с видео
# git - нужен, если какие-то питон-либы ставятся через git
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Создаем папки для работы, чтобы избежать ошибок прав доступа
RUN mkdir -p uploads temp

# Копируем код приложения
COPY app ./app

# Открываем порт
EXPOSE 8000

# Запускаем приложение
# host 0.0.0.0 обязательно для Докера
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]