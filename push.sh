#!/bin/bash

# Добавляем все изменения
git add .

# Спрашиваем описание коммита (необязательно, можно захардкодить)
echo "Введите описание коммита (или нажмите Enter для стандартного):"
read message
if [ -z "$message" ]; then
  message="Обновление проекта: $(date +'%Y-%m-%d %H:%M:%S')"
fi

# Коммит и Пуш
git commit -m "$message"
git push

echo "Готово! Изменения отправлены в GitHub."
