# Стандарт отказоустойчивости

## Триггеры: когда думать о fault tolerance

При написании кода **остановись и подумай "что если сломается?"**, если ты:

- Вызываешь внешний API/сервис → что если таймаут, 5xx, недоступен? Retry с backoff, circuit breaker, fallback
- Пишешь в БД → что если constraint violation, deadlock, connection lost? Транзакции, retry, graceful error
- Обрабатываешь платёж или многошаговую операцию → что если сбой между шагами? Идемпотентность, saga, compensation
- Работаешь с файлами/S3 → что если partial write, disk full, permission denied? Atomic write (temp + rename), cleanup
- Запускаешь фоновую задачу/job → что если crash mid-job? Retry policy, checkpoint, dead letter queue
- Распределённая операция → что если часть нод недоступна? Timeout, partial failure handling, eventual consistency
- Принимаешь пользовательский ввод → что если невалидные данные, injection, overflow? Валидация на границе

## Что делать когда триггер сработал

1. **Определи failure mode** — что конкретно может пойти не так?
2. **Определи impact** — что произойдёт с пользователем/системой?
3. **Выбери стратегию:**
   - Retry (transient errors) — с exponential backoff и max attempts
   - Fallback (degraded mode) — вернуть кешированные данные, показать заглушку
   - Circuit breaker (cascading failures) — прекратить вызовы к упавшему сервису
   - Compensation (partial failure) — откатить завершённые шаги
   - Fail fast (unrecoverable) — вернуть понятную ошибку, не зависнуть
4. **Залогируй** — каждый failure path должен быть залогирован (см. logging-standard)

## Когда НЕ нужно

- Конфигурационные файлы, DTO, модели без логики
- UI-компоненты без серверного взаимодействия
- Юнит-тесты
- Одноразовые скрипты и миграции
- Внутренние pure-функции без I/O
