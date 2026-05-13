# AGUI Idea

## Коротко

**AGUI** это generative human experience runtime для AI-агентов.

Пользователь описывает задачу обычным языком. AGUI понимает, что нужно сделать, сам ищет подходящие инструменты через MCP, CLI, API или локальные адаптеры, подключает их, планирует выполнение и генерирует лучший способ показать человеку процесс, выборы, риски и результат.

AGUI не является обычным чат-интерфейсом. AGUI не является набором готовых React-блоков. AGUI каждый раз принимает форму задачи.

Иногда это полноценное мини-приложение. Иногда статус-панель. Иногда отчёт. Иногда дашборд. Иногда экран подтверждения опасного действия. Иногда вообще не нужен интерфейс, нужен только аккуратный финальный ответ.

Главная формула:

```text
AGUI = Tool Discovery + Task Execution + Generative Human Experience
```

## Главная идея

Современные AI-агенты умеют вызывать инструменты, но человек часто видит только чат и куски логов. Это плохо подходит для реальных задач.

Если агент ищет блогеров, человеку нужен не просто текст “ищу”. Ему нужна живая scouting-панель: какие источники проверяются, сколько кандидатов найдено, кто отсеян и почему.

Если агент анализирует CSV, человеку нужен upload, настройки, таблица дублей, фильтры, экспорт.

Если агент деплоит проект, человеку нужна deploy-консоль: шаги, логи, ошибки, rollback, подтверждения.

Если агент сравнивает платежки, человеку нужна decision board: карточки, таблица плюсов и минусов, риски, рекомендации.

AGUI должен сам решить, какой формат лучше подходит для задачи.

## Что AGUI делает

1. Принимает пользовательский intent.
2. Понимает тип задачи.
3. Решает, нужен ли интерфейс и какой именно.
4. Ищет подходящие инструменты:
   - MCP servers;
   - CLI tools;
   - API adapters;
   - local scripts;
   - OpenAPI specs;
   - Docker tools;
   - внутренние toolpacks.
5. Проверяет инструменты на применимость и риск.
6. Подключает или предлагает подключить инструменты.
7. Получает схемы инструментов, параметры, описания, permissions.
8. Планирует выполнение.
9. Генерирует task-specific HTML, CSS и JS.
10. Запускает интерфейс в sandbox.
11. Выполняет действия через безопасный bridge.
12. Обновляет интерфейс по ходу выполнения.
13. Показывает результат в форме, которая лучше всего подходит человеку.

## Чем AGUI не является

AGUI не должен быть просто “чатом с кнопками”.

AGUI не должен быть статичным dashboard builder.

AGUI не должен быть Retool-клоном, где человек руками собирает формы.

AGUI не должен быть библиотекой UI-компонентов, где агент выбирает из пары блоков.

AGUI не должен всегда генерировать большой интерфейс. Иногда лучший интерфейс это маленькая, но умная статус-панель.

## Ключевой принцип

```text
Не человек подстраивается под софт.
Софт каждый раз принимает форму задачи.
```

AGUI должен думать не только о выполнении, но и о человеческом восприятии:

- что сейчас происходит;
- почему это происходит;
- сколько уже сделано;
- что будет дальше;
- где нужен выбор человека;
- где нужен риск-контроль;
- как лучше показать результат;
- нужен ли вообще интерфейс.

## Presentation Planner

Центральный слой AGUI это **Presentation Planner**.

Он отвечает на вопрос:

```text
Как человеку лучше показать эту задачу, её выполнение и результат?
```

Возможные режимы:

```ts
type PresentationMode =
  | "answer_only"
  | "status_view"
  | "progress_console"
  | "generated_app"
  | "decision_board"
  | "approval_flow"
  | "report"
  | "dashboard"
  | "wizard"
  | "debug_console"
  | "timeline";
```

### answer_only

Используется, когда задача простая и интерфейс только мешает.

Пример:

```text
Пользователь: Объясни, что такое MCP.
AGUI: Даёт обычный структурированный ответ.
```

### status_view

Используется, когда пользователь сказал “сделай”, а не “дай мне настроить”.

Пример:

```text
Пользователь: Найди блогеров для FasonAI с бюджетом 5-10к.
AGUI: Генерирует уникальную scouting-панель с прогрессом, этапами, найденными кандидатами и текущим действием.
```

### progress_console

Используется для технических задач, где важны шаги, логи, ошибки и retry.

Пример:

```text
Пользователь: Задеплой проект.
AGUI: Показывает deploy-консоль, build logs, env checks, health checks и rollback controls.
```

### generated_app

Используется, когда человеку нужно загрузить данные, настроить параметры, выбрать варианты или работать с результатом.

Пример:

```text
Пользователь: Проверь CSV на дубли.
AGUI: Генерирует мини-приложение с upload, настройками, таблицей, фильтрами и экспортом.
```

### decision_board

Используется для выбора между несколькими вариантами.

Пример:

```text
Пользователь: Подбери платежку для SaaS.
AGUI: Показывает карточки вариантов, сравнительную таблицу, риски и рекомендацию.
```

### approval_flow

Используется для опасных или необратимых действий.

Пример:

```text
Пользователь: Удали старые файлы.
AGUI: Показывает dry-run, список изменений, риск, подтверждение и только потом выполняет действие.
```

### report

Используется, когда важен итоговый документ.

Пример:

```text
Пользователь: Подготовь маркетинговый аудит.
AGUI: Собирает отчёт с выводами, таблицами, ссылками, приоритетами и next steps.
```

### dashboard

Используется, когда задача связана с мониторингом или большим количеством метрик.

Пример:

```text
Пользователь: Проверь состояние проекта.
AGUI: Показывает health dashboard: тесты, CI, issues, деплой, ошибки, latency.
```

## UI Generator

UI Generator в AGUI не должен собирать интерфейс только из заранее заданных блоков.

Он должен генерировать полноценный task-specific mini app:

- HTML;
- CSS;
- JavaScript;
- layout;
- visual style;
- microcopy;
- progress states;
- empty states;
- error states;
- result states.

Каждый интерфейс может быть уникальным по дизайну и поведению.

Пример одного интерфейса:

```text
CSV Analyzer
- строгий data tool;
- таблицы;
- upload;
- фильтры;
- экспорт.
```

Пример другого интерфейса:

```text
Influencer Scout
- радар поиска;
- карточки блогеров;
- budget fit;
- engagement score;
- причины отбора.
```

Пример третьего интерфейса:

```text
Deploy Console
- терминальный стиль;
- timeline шагов;
- build logs;
- кнопка rollback;
- health check.
```

Важно: UI не должен быть халтурным “loading bar”. Если задача разная, статус-экран тоже должен быть разный.

## Safe Generated Runtime

Сгенерированный HTML/CSS/JS нельзя запускать как попало.

AGUI должен запускать generated UI в sandboxed iframe.

Сгенерированный JS не должен иметь прямого доступа к системе, токенам, MCP-серверам, локальным файлам, cookies или основному DOM.

Все действия должны идти через контролируемый bridge:

```js
window.agui.callTool(toolName, params)
window.agui.searchTools(query)
window.agui.getState()
window.agui.setState(patch)
window.agui.askApproval(action)
window.agui.onTaskUpdate(callback)
window.agui.showToast(message)
```

Правильный runtime:

```text
Generated HTML/CSS/JS
→ sandboxed iframe
→ AGUI Bridge
→ Permission Layer
→ Tool Broker
→ MCP / CLI / API
```

## Tool Discovery

AGUI должен не только использовать уже подключённые инструменты, но и искать новые.

Источники поиска:

- локальные MCP-конфиги;
- публичные MCP-каталоги;
- GitHub repositories;
- npm packages;
- PyPI packages;
- Docker images;
- OpenAPI specifications;
- CLI tools на машине;
- user-defined toolpacks;
- remote MCP endpoints.

Tool Discovery должен уметь:

1. Найти кандидаты.
2. Понять, что они делают.
3. Проверить документацию.
4. Определить способ установки.
5. Определить permissions.
6. Оценить риск.
7. Подключить через sandbox.
8. Получить tools/list или аналогичную схему.
9. Сохранить инструмент в registry.

## Capability Registry

Все найденные инструменты должны приводиться к единой модели:

```ts
type Capability = {
  id: string;
  source: "mcp" | "cli" | "api" | "local" | "openapi";
  name: string;
  title: string;
  description: string;
  inputSchema?: unknown;
  outputSchema?: unknown;
  install?: {
    type: "npx" | "uvx" | "docker" | "binary" | "remote";
    command?: string;
  };
  permissions: Permission[];
  risk: "read" | "write" | "destructive" | "network" | "filesystem" | "secret";
  trustScore: number;
  examples?: string[];
};
```

Capability Registry нужен, чтобы агент не каждый раз начинал с нуля.

## Execution Broker

Execution Broker отвечает за реальное выполнение действий.

Он должен поддерживать:

- MCP tools/call;
- CLI command execution;
- API calls;
- local script execution;
- Docker sandbox;
- long-running jobs;
- streaming logs;
- cancellation;
- retry;
- dry-run;
- approval checkpoints.

Любое действие должно проходить через broker, а не напрямую из generated UI.

## Permission Layer

AGUI должен быть безопасным по умолчанию.

Для каждого инструмента нужно понимать:

- читает ли он данные;
- пишет ли он данные;
- может ли удалить данные;
- требует ли токены;
- работает ли с сетью;
- работает ли с файловой системой;
- может ли запускать код;
- нужен ли human approval.

Примеры правил:

```text
read-only tool → можно запускать без подтверждения
write tool → нужно явное подтверждение
destructive tool → dry-run + подтверждение
secret access → отдельное разрешение
deploy/payment/DNS → всегда approval_flow
```

## Task State

AGUI должен хранить состояние задачи как объект, а не только историю сообщений.

Пример:

```json
{
  "taskId": "influencer_search_001",
  "goal": "Найти блогеров для FasonAI",
  "presentationMode": "status_view",
  "status": "running",
  "currentStep": "filtering_by_budget",
  "tools": ["web_search", "instagram_lookup", "spreadsheet_export"],
  "metrics": {
    "found": 43,
    "matched": 17,
    "rejected": 26
  },
  "result": null
}
```

Task State должен обновлять generated UI через events.

## Event Stream

AGUI должен передавать интерфейсу live events:

```ts
type TaskEvent =
  | { type: "step_started"; step: string; message: string }
  | { type: "step_completed"; step: string; result?: unknown }
  | { type: "progress"; percent?: number; metrics?: Record<string, unknown> }
  | { type: "tool_called"; tool: string; paramsPreview?: unknown }
  | { type: "tool_result"; tool: string; resultPreview?: unknown }
  | { type: "approval_required"; action: unknown }
  | { type: "error"; message: string; recoverable: boolean }
  | { type: "final_result"; result: unknown };
```

Generated UI должен не просто показывать progress bar, а визуализировать эти события в форме, подходящей задаче.

## Пример сценария: поиск блогеров

Пользователь:

```text
Найди блогеров в Instagram для рекламы FasonAI. Бюджет 5-10к рублей.
```

AGUI решает:

```json
{
  "taskType": "research_and_selection",
  "needsFullApp": false,
  "needsUserInput": false,
  "presentationMode": "status_view",
  "visualConcept": "influencer_scouting_radar"
}
```

AGUI ищет инструменты:

```text
web search
social profile lookup
spreadsheet export
contact enrichment
```

AGUI генерирует статус-панель:

```text
- радар поиска;
- этапы scouting;
- счётчик найденных аккаунтов;
- счётчик подходящих аккаунтов;
- причины отсева;
- текущий источник;
- предварительные карточки кандидатов.
```

В конце AGUI показывает:

```text
- таблицу блогеров;
- предполагаемую цену;
- почему подходит;
- риск накрутки;
- контакт;
- формат рекламы;
- рекомендацию, кому писать первым.
```

## Пример сценария: проверка CSV на дубли

Пользователь:

```text
Проверь выгрузку обращений на дубли.
```

AGUI решает:

```json
{
  "taskType": "data_processing",
  "needsFullApp": true,
  "needsUserInput": true,
  "presentationMode": "generated_app",
  "visualConcept": "data_cleaning_workbench"
}
```

AGUI генерирует интерфейс:

```text
- upload CSV;
- выбор кодировки;
- настройка процента похожести;
- чекбокс “только один Автор”;
- preview колонок;
- кнопка запуска;
- таблица групп дублей;
- текст для закрытия;
- экспорт отчёта.
```

## Пример сценария: деплой

Пользователь:

```text
Задеплой проект.
```

AGUI решает:

```json
{
  "taskType": "devops_execution",
  "needsFullApp": false,
  "needsUserInput": "maybe",
  "presentationMode": "progress_console",
  "visualConcept": "deploy_control_room"
}
```

AGUI показывает:

```text
- проверка репозитория;
- проверка env;
- build;
- tests;
- deploy;
- health check;
- rollback button;
- логи;
- ошибки с объяснением.
```

Для опасных действий AGUI переключается в approval_flow.

## Архитектура

```text
apps/api
  agents/
    task_planner.py
    tool_finder.py
    presentation_planner.py
    ui_codegen.py
    executor.py

  discovery/
    github_search.py
    mcp_registry_search.py
    npm_search.py
    pypi_search.py
    local_mcp_scan.py
    cli_scan.py

  tools/
    mcp_client.py
    cli_adapter.py
    openapi_adapter.py
    tool_broker.py
    permission_guard.py
    sandbox.py

  runtime/
    task_state.py
    event_stream.py
    approval.py
    audit_log.py

apps/web
  GeneratedExperienceFrame.tsx
  AguiBridge.ts
  ApprovalModal.tsx
  RuntimeConsole.tsx
  TaskEventStream.ts
```

## Минимальный MVP

Первый MVP не должен пытаться закрыть всё.

Нужен один сильный вертикальный сценарий:

```text
User Intent
→ Tool Discovery
→ Tool Selection
→ Presentation Planning
→ HTML/CSS/JS generation
→ sandbox iframe
→ bridge calls
→ live status updates
→ final result
```

Лучшие MVP-сценарии:

1. CSV Analyzer.
2. GitHub repo reviewer.
3. Website audit.
4. Influencer scouting.
5. Deploy assistant.

Самый понятный первый сценарий:

```text
CSV Analyzer
```

Почему:

- легко показать upload;
- легко показать generated app;
- легко показать progress;
- легко показать таблицы;
- легко показать export;
- понятная польза.

## Продуктовое позиционирование

AGUI это не “ещё один AI chat”.

AGUI это:

```text
An agent runtime that generates the right interface for the task.
```

Или:

```text
A generative interface layer for MCP and CLI agents.
```

Или по-русски:

```text
Среда, где агент сам находит инструменты и сам придумывает лучший интерфейс для выполнения задачи.
```

## Главный вау-эффект

Пользователь пишет одну фразу, а AGUI отвечает не только текстом.

Он может создать:

- маленькую панель наблюдения;
- полноценное приложение;
- красивый отчёт;
- интерактивный выбор;
- консоль выполнения;
- безопасный экран подтверждения;
- дашборд состояния.

И всё это не заранее нарисовано вручную, а сгенерировано под конкретную задачу.

## Критерии успеха

AGUI работает правильно, если:

1. Пользователь не думает о том, какие инструменты нужны.
2. Пользователь не думает о том, какой интерфейс нужен.
3. Агент сам выбирает способ подачи.
4. Generated UI выглядит уместно для конкретной задачи.
5. Статус выполнения понятен человеку.
6. Опасные действия требуют подтверждения.
7. Инструменты вызываются только через безопасный bridge.
8. Результат представлен в форме, с которой удобно работать.
9. Каждая задача ощущается как маленькое кастомное приложение.

## Самая короткая версия идеи

```text
AGUI превращает намерение пользователя в найденные инструменты, безопасное выполнение и уникальный интерфейс под задачу.
```

## Финальная формула

```text
Intent → Tools → Execution → Human Experience
```

AGUI должен быть слоем, где агент не просто отвечает, а создаёт форму взаимодействия под задачу.
