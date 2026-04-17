import os
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.auth import create_token, get_current_user, require_admin
from app.db import execute, fetch_all, fetch_one, hash_password, init_db, verify_password
from app.env import load_env
from app.services.docker_control import is_server_running, start_server
from app.services.llm_client import generate_completion, transcribe_audio
from app.services.rag import index_document, search_knowledge


load_env()
PORT = int(os.getenv("PORT", "8000"))
ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="AutoAI RMKD", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AuthPayload(BaseModel):
    identifier: str = Field(min_length=3)
    password: str = Field(min_length=4)


class IdeaPayload(BaseModel):
    problem: str
    transcript: str = ""
    context: str = ""


class SearchPayload(BaseModel):
    query: str


class DocumentPayload(BaseModel):
    title: str
    folder: str = "Протоколы сессий"
    content: str = ""
    tool: str = "СОП"


class TemplatePayload(BaseModel):
    template_name: str


class ChatPayload(BaseModel):
    prompt: str


class UserSettingsPayload(BaseModel):
    model_mode: str


TEMPLATES: dict[str, str] = {
    "6С": "1) Объект 6С\n2) Текущее состояние\n3) Отклонения\n4) План 6С\n5) Сроки\n6) Ответственные\n7) Эффект",
    "СОП": "1) Цель СОП\n2) Область применения\n3) Пошаговый процесс\n4) Контрольные точки\n5) Риски\n6) KPI",
    "SMED": "1) Описание переналадки\n2) Внутренние/внешние операции\n3) Потери времени\n4) План сокращения\n5) Экономический эффект",
    "TPM": "1) Оборудование\n2) Тип потерь\n3) Причины отказов\n4) Мероприятия TPM\n5) План обслуживания\n6) Эффект",
}


@app.on_event("startup")
def on_startup() -> None:
    init_db(ADMIN_LOGIN, ADMIN_PASSWORD)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/auth/register")
def register(payload: AuthPayload):
    exists = fetch_one("SELECT id FROM users WHERE identifier = ?", (payload.identifier,))
    if exists:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")
    user_id = execute(
        "INSERT INTO users(identifier, password_hash, role) VALUES(?,?,?)",
        (payload.identifier, hash_password(payload.password), "user"),
    )
    execute("INSERT OR REPLACE INTO user_settings(user_id, model_mode) VALUES(?,?)", (user_id, "server"))
    token = create_token(user_id=user_id, role="user", identifier=payload.identifier)
    return {"token": token, "user": {"id": user_id, "identifier": payload.identifier, "role": "user"}}


@app.post("/api/auth/login")
def login(payload: AuthPayload):
    user = fetch_one("SELECT id, identifier, password_hash, role FROM users WHERE identifier = ?", (payload.identifier,))
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = create_token(user_id=user["id"], role=user["role"], identifier=user["identifier"])
    return {"token": token, "user": {"id": user["id"], "identifier": user["identifier"], "role": user["role"]}}


@app.get("/api/me")
def me(user: dict = Depends(get_current_user)):
    settings = fetch_one("SELECT model_mode FROM user_settings WHERE user_id = ?", (user["id"],))
    return {**user, "model_mode": settings["model_mode"] if settings else "server"}


@app.get("/api/server/status")
def server_status(user: dict = Depends(get_current_user)):
    return {"running": is_server_running(), "requested_by": user["identifier"]}


@app.post("/api/server/start")
def server_start(admin: dict = Depends(require_admin)):
    started, message = start_server()
    return {"started": started, "message": message, "requested_by": admin["identifier"]}


@app.post("/api/analysis/transcribe")
async def analysis_transcribe(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    _ = user
    data = await file.read()
    try:
        text = transcribe_audio(data, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка транскрипции: {exc}") from exc
    return {"transcript": text}


@app.post("/api/analysis/extract-ideas")
def analysis_extract(payload: IdeaPayload, user: dict = Depends(get_current_user)):
    rag_items = search_knowledge(payload.problem or payload.context, top_k=3)
    rag_context = "\n".join([f"[{x['source_name']}] {x['chunk_text']}" for x in rag_items]) or "Нет контекста"
    prompt = (
        f"Проблема: {payload.problem}\n\n"
        f"Транскрипт: {payload.transcript}\n\n"
        f"Допконтекст: {payload.context}\n\n"
        f"RAG контекст:\n{rag_context}\n\n"
        "Сделай выжимку идей, выдели 5 пунктов, предложи инструмент (6С/СОП/SMED/TPM), "
        "и какие поля паспорта проекта заполнить в первую очередь."
    )
    try:
        result = generate_completion(
            system_prompt="Ты ИИ-помощник отдела улучшений горно-металлургической компании.",
            user_prompt=prompt,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка LLM: {exc}") from exc
    execute(
        "INSERT INTO chat_metrics(user_id, prompt, response_ms, tokens_out, tokens_per_sec) VALUES(?,?,?,?,?)",
        (user["id"], payload.problem, result["elapsed_ms"], result["tokens_out"], result["tokens_per_sec"]),
    )
    return {"analysis": result["text"], "metrics": result, "similar_cases": [item["source_name"] for item in rag_items]}


@app.post("/api/rag/upload")
async def rag_upload(tool: str, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    _ = user
    raw = await file.read()
    text = raw.decode("utf-8", errors="ignore")
    if not text.strip():
        raise HTTPException(status_code=400, detail="Файл пустой или не удалось декодировать")
    chunks = index_document(file.filename, text, tool=tool)
    return {"source": file.filename, "chunks_indexed": chunks, "tool": tool}


@app.post("/api/rag/search")
def rag_search(payload: SearchPayload, user: dict = Depends(get_current_user)):
    _ = user
    return {"items": search_knowledge(payload.query, top_k=7)}


@app.get("/api/templates")
def templates(user: dict = Depends(get_current_user)):
    _ = user
    return {"items": [{"name": name, "content": content} for name, content in TEMPLATES.items()]}


@app.get("/api/documents")
def list_documents(user: dict = Depends(get_current_user)):
    rows = fetch_all(
        "SELECT id, title, folder, content, tool, created_at FROM documents WHERE created_by = ? ORDER BY id DESC",
        (user["id"],),
    )
    return {"items": [dict(row) for row in rows]}


@app.post("/api/documents")
def create_document(payload: DocumentPayload, user: dict = Depends(get_current_user)):
    doc_id = execute(
        "INSERT INTO documents(title, folder, content, tool, created_by) VALUES(?,?,?,?,?)",
        (payload.title, payload.folder, payload.content, payload.tool, user["id"]),
    )
    return {"id": doc_id}


@app.put("/api/documents/{doc_id}")
def update_document(doc_id: int, payload: DocumentPayload, user: dict = Depends(get_current_user)):
    execute(
        "UPDATE documents SET title = ?, folder = ?, content = ?, tool = ? WHERE id = ? AND created_by = ?",
        (payload.title, payload.folder, payload.content, payload.tool, doc_id, user["id"]),
    )
    return {"updated": True}


@app.post("/api/documents/{doc_id}/apply-template")
def apply_template(doc_id: int, payload: TemplatePayload, user: dict = Depends(get_current_user)):
    template = TEMPLATES.get(payload.template_name)
    if not template:
        raise HTTPException(status_code=400, detail="Неизвестный шаблон")
    row = fetch_one("SELECT content FROM documents WHERE id = ? AND created_by = ?", (doc_id, user["id"]))
    if not row:
        raise HTTPException(status_code=404, detail="Документ не найден")
    new_content = f"{row['content']}\n\n---\nПримененный шаблон {payload.template_name}\n{template}".strip()
    execute("UPDATE documents SET content = ? WHERE id = ? AND created_by = ?", (new_content, doc_id, user["id"]))
    return {"applied": True, "template": payload.template_name}


@app.post("/api/chat")
def chat(payload: ChatPayload, user: dict = Depends(get_current_user)):
    prompt = (
        "Ты агент по документообороту отдела улучшений. Отвечай структурно и предлагай следующие шаги.\n\n"
        f"Запрос пользователя:\n{payload.prompt}"
    )
    try:
        result = generate_completion(system_prompt="Ты корпоративный AI-помощник.", user_prompt=prompt)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Ошибка LLM: {exc}") from exc
    execute(
        "INSERT INTO chat_metrics(user_id, prompt, response_ms, tokens_out, tokens_per_sec) VALUES(?,?,?,?,?)",
        (user["id"], payload.prompt, result["elapsed_ms"], result["tokens_out"], result["tokens_per_sec"]),
    )
    return {"answer": result["text"], "metrics": result}


@app.get("/api/chat/metrics")
def chat_metrics(user: dict = Depends(get_current_user)):
    rows = fetch_all(
        "SELECT prompt, response_ms, tokens_out, tokens_per_sec, created_at FROM chat_metrics WHERE user_id = ? ORDER BY id DESC LIMIT 20",
        (user["id"],),
    )
    return {"items": [dict(row) for row in rows]}


@app.get("/api/settings")
def get_settings(user: dict = Depends(get_current_user)):
    settings = fetch_one("SELECT model_mode FROM user_settings WHERE user_id = ?", (user["id"],))
    return {"model_mode": settings["model_mode"] if settings else "server"}


@app.put("/api/settings")
def set_settings(payload: UserSettingsPayload, user: dict = Depends(get_current_user)):
    if payload.model_mode not in {"server", "local", "api"}:
        raise HTTPException(status_code=400, detail="Допустимые режимы: server/local/api")
    execute("INSERT OR REPLACE INTO user_settings(user_id, model_mode) VALUES(?,?)", (user["id"], payload.model_mode))
    return {"saved": True, "model_mode": payload.model_mode}


@app.get("/api/jira/import")
def jira_import(user: dict = Depends(get_current_user)):
    _ = user
    # MVP: заглушка импорта из Jira SM
    return {
        "items": [
            {"id": "JSM-101", "title": "Снижение простоев насосов", "tool": "TPM"},
            {"id": "JSM-102", "title": "Сокращение времени переналадки пресса", "tool": "SMED"},
            {"id": "JSM-103", "title": "Стандартизация чек-листа обслуживания", "tool": "СОП"},
        ]
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=PORT, reload=True)
