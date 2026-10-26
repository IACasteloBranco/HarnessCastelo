import json
from pathlib import Path
from playwright.sync_api import sync_playwright


BASE = "https://localhost:18443/"


def mock(route, body, status=200, content_type="application/json", headers=None):
    route.fulfill(status=status, content_type=content_type,
                  headers=headers or {}, body=body if isinstance(body, str) else json.dumps(body))


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, executable_path="/opt/google/chrome/chrome",
                                         args=["--no-sandbox", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
    for role, screenshot in [("collaborator", "/tmp/maximus-chat-preview.png"), ("governance", "/tmp/maximus-governance-preview.png")]:
        context = browser.new_context(viewport={"width": 1448, "height": 1086}, ignore_https_errors=True)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        calls = []
        sent = []
        titles = []
        artifacts = []

        def handle(route):
            request = route.request
            path = request.url.split("/api/", 1)[1]
            calls.append(path)
            if path == "auth/me":
                return mock(route, {"employee_code": "COLAB001", "role": role,
                                    "can_govern": role == "collaborator", "must_change_password": False})
            if path == "oauth/credentials":
                return mock(route, [{"credential_id": "CONTA01", "connected": True, "can_connect": True}])
            if path == "chat/projects":
                return mock(route, {"projects": []})
            if path.startswith("chat/history"):
                runs = [{"run_id": f"11111111-1111-4111-8111-{index:012d}", "client_message_id": item["client_message_id"], "prompt": item["text"],
                         "attachments": [{"id": "33333333-3333-4333-8333-333333333333", "name": file["name"], "size": 15} for file in item.get("attachments", [])],
                         "artifacts": artifacts if index == 1 else [],
                         "response": {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Resposta de teste"}]}]}, "outcome": "completed"}
                        for index, item in enumerate(sent, 1)]
                return mock(route, {"conversation_id": "22222222-2222-4222-8222-222222222222" if sent else None, "project_id": None, "title": titles[-1] if titles else None, "runs": runs})
            if path.startswith("chat/conversations?"):
                return mock(route, {"conversations": [{"id": "22222222-2222-4222-8222-222222222222", "project_id": None, "title": titles[-1] if titles else None, "snippet": None, "match_run_id": None}] if sent else [], "next_before": None})
            if path.endswith("/suggest-title"):
                return mock(route, {"title": "Título sugerido"})
            if path.startswith("chat/conversations/"):
                titles.append(request.post_data_json["title"])
                return mock(route, {"title": titles[-1]})
            if path == "chat/transcriptions":
                return mock(route, {"text": "Áudio transcrito para revisão."})
            if path == "chat/messages":
                sent.append(request.post_data_json)
                answer = {"type": "response.completed", "response": {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Resposta de teste"}]}]}}
                return mock(route, 'event: response.output_text.delta\ndata: {"delta":"Resposta de "}\n\nevent: response.output_text.delta\ndata: {"delta":"teste"}\n\nevent: response.completed\ndata: ' + json.dumps(answer) + '\n\n', content_type="text/event-stream", headers={"X-Conversation-ID": "22222222-2222-4222-8222-222222222222", "X-Run-ID": f"11111111-1111-4111-8111-{len(sent):012d}"})
            if path == "chat/attachments/33333333-3333-4333-8333-333333333333":
                return route.fulfill(status=200, body=b"dados ficticios", headers={
                    "Content-Type": "text/plain", "Content-Disposition": "attachment; filename=notas.txt"})
            if path == "chat/attachments/33333333-3333-4333-8333-333333333333/preview":
                return mock(route, {"text": "dados ficticios", "truncated": False})
            if path.endswith("/artifacts") and path.startswith("chat/runs/"):
                format = request.post_data_json["format"]
                artifact = {"id": "44444444-4444-4444-8444-444444444444" if format == "pdf" else "55555555-5555-4555-8555-555555555555",
                            "name": f"maximus-teste.{format}", "format": format, "size": 16}
                artifacts.append(artifact)
                return mock(route, artifact)
            if path == "chat/artifacts/55555555-5555-4555-8555-555555555555/preview":
                return mock(route, {"columns": ["Item", "Quantidade"], "rows": [["A", "5"]], "truncated": False})
            if path == "chat/artifacts/44444444-4444-4444-8444-444444444444/preview":
                return route.fulfill(status=200, body=b"%PDF-1.4\n%%EOF\n", headers={
                    "Content-Type": "application/pdf", "Content-Disposition": "inline"})
            if path == "chat/artifacts/44444444-4444-4444-8444-444444444444":
                return route.fulfill(status=200, body=b"%PDF-1.4\n%%EOF\n", headers={
                    "Content-Type": "application/pdf", "Content-Disposition": "attachment; filename=maximus-teste.pdf"})
            if path.startswith("governance/reports/daily"):
                return mock(route, {"usage": [{"day": "2026-10-25", "department": "CONTABIL", "runs": 3, "errors": 1, "latency_ms": 3000, "latency_samples": 2}], "findings": [{"day": "2026-10-25", "department": "CONTABIL", "category": "sensitive_data", "count": 1}]})
            if path == "governance/runs":
                return mock(route, {"runs": [{"run_id": "11111111-1111-4111-8111-111111111111", "outcome": "completed", "started_at": "2026-10-25T10:00:00Z"}]})
            if path == "governance/findings":
                return mock(route, {"findings": []})
            if path == "governance/alerts":
                return mock(route, {"alerts": []})
            if path.startswith("governance/runs/"):
                return mock(route, {"run_id": "11111111-1111-4111-8111-111111111111", "request": {"input": [{"role": "user", "content": "teste"}]}})
            return mock(route, {}, status=404)

        page.route("**/api/**", handle)
        page.goto(BASE)
        if role == "collaborator":
            page.get_by_role("heading", name="Como posso ajudar hoje?").wait_for()
            page.locator("#chat-sidebar-governance").click()
            page.get_by_role("heading", name="Visão de uso").wait_for()
            page.locator("#chat-nav").click()
            page.get_by_role("heading", name="Como posso ajudar hoje?").wait_for()
            assert page.locator("#chat-side-user").is_visible()
            assert not page.locator("#chat-header-logout").is_visible()
            page.locator("#chat-side-user").click()
            assert page.locator("#chat-user-menu").is_visible()
            page.screenshot(path="/tmp/maximus-chat-profile-menu.png", full_page=True)
            page.keyboard.press("Escape")
            assert not page.locator("#chat-user-menu").is_visible()
            assert not page.locator(".credential-picker").is_visible()
            assert not page.locator("#chat-header-accounts").is_visible()
            assert page.locator("#chat-credential").input_value() == "CONTA01"
            page.screenshot(path="/tmp/maximus-chat-empty-preview.png", full_page=True)
            page.set_viewport_size({"width": 1672, "height": 941})
            page.screenshot(path="/tmp/maximus-chat-reference-size.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.locator("#chat-side-user").is_visible()
            page.locator("#chat-side-user").click()
            assert page.locator("#chat-sidebar-logout").is_visible()
            assert page.locator("#chat-menu-governance").is_visible()
            page.keyboard.press("Escape")
            page.screenshot(path="/tmp/maximus-chat-empty-mobile.png", full_page=True)
            page.locator("#chat-add-menu summary").click()
            assert page.get_by_role("button", name="Transcrever áudio").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path="/tmp/maximus-chat-add-menu-mobile.png")
            page.keyboard.press("Escape")
            assert not page.locator("#chat-add-menu").evaluate("element => element.open")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.set_viewport_size({"width": 1448, "height": 1086})
            page.locator("#chat-text").fill("Olá")
            page.locator("#chat-form button[type=submit]").click()
            page.get_by_text("Resposta de teste").wait_for()
            assert page.locator(".chat-bubble strong").count() == 0
            page.locator(".chat-artifact-menu summary").first.click()
            page.locator(".chat-artifact-menu button", has_text="PDF").first.click()
            page.locator("#artifact-dialog").wait_for(state="visible")
            assert page.locator("#artifact-dialog iframe").count() == 1
            with page.expect_download() as generated_download:
                page.locator("#artifact-dialog-download").click()
            assert generated_download.value.suggested_filename == "maximus-teste.pdf"
            page.locator("#artifact-dialog-close").click()
            page.get_by_role("button", name="Visualizar maximus-teste.pdf").click()
            page.locator("#artifact-dialog").wait_for(state="visible")
            page.keyboard.press("Escape")
            assert not page.locator("#artifact-dialog").is_visible()
            page.locator(".chat-artifact-menu summary").first.click()
            page.locator(".chat-artifact-menu button", has_text="CSV").first.click()
            page.locator("#artifact-dialog-body table").wait_for()
            assert page.locator("#artifact-dialog-body td").first.text_content() == "A"
            page.screenshot(path="/tmp/maximus-artifact-table-preview.png")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path="/tmp/maximus-artifact-table-mobile.png")
            page.set_viewport_size({"width": 1448, "height": 1086})
            page.locator("#artifact-dialog-close").click()
            assistant_background = page.locator(".chat-bubble.assistant").evaluate("element => getComputedStyle(element).backgroundColor")
            assert assistant_background in ("rgba(0, 0, 0, 0)", "transparent"), assistant_background
            assert len(sent) == 1 and sent[0]["text"] == "Olá" and sent[0]["model"] == "gpt-6-luna"
            page.get_by_label("Opções para Conversa sem título").click()
            assert page.get_by_role("button", name="Renomear").is_visible()
            assert page.get_by_role("button", name="Excluir").is_visible()
            page.screenshot(path="/tmp/maximus-conversation-menu.png")
            page.get_by_role("button", name="Renomear").click()
            page.locator("#chat-title-input").fill("Dúvidas de teste")
            page.locator("#chat-title-form button[type=submit]").click()
            page.get_by_text("Dúvidas de teste").first.wait_for()
            assert titles == ["Dúvidas de teste"]
            page.get_by_label("Opções para Dúvidas de teste").click()
            page.once("dialog", lambda dialog: dialog.dismiss())
            page.get_by_role("button", name="Excluir").click()
            assert page.get_by_label("Opções para Dúvidas de teste").count() == 1
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#chat-mobile-list").click()
            page.get_by_label("Opções para Dúvidas de teste").click()
            assert page.get_by_role("button", name="Renomear").is_visible()
            page.screenshot(path="/tmp/maximus-conversation-menu-mobile.png")
            page.set_viewport_size({"width": 1448, "height": 1086})
            assert sent[0]["client_message_id"]
            partial = page.evaluate("""async () => {
              const pending = {answer: ""};
              const bytes = new TextEncoder().encode('event: response.output_text.delta\\ndata: {"delta":"Parcial"}\\n\\n');
              const stream = new ReadableStream({start(controller) {
                controller.enqueue(bytes.slice(0, 37));
                controller.enqueue(bytes.slice(37));
                controller.close();
              }});
              await readChatStream(new Response(stream), pending);
              return pending.answer;
            }""")
            assert partial == "Parcial"
            assert page.evaluate("requestsPdf('Faça um resumo em PDF para baixar')")
            assert not page.evaluate("requestsPdf('Você não consegue gerar um PDF pra eu baixar aqui pelo chat não?')")
            assert not page.evaluate("requestsPdf('Não quero gerar PDF desse relatório')")
            markup = page.evaluate("""() => {
              const bubble = chatBubble('assistant', '# Título\\n\\n- item\\n\\n<script>window.bad = true</script>');
              document.body.append(bubble);
              const result = {heading: !!bubble.querySelector('h1'), item: !!bubble.querySelector('li'),
                script: !!bubble.querySelector('script'), escaped: bubble.textContent.includes('<script>')};
              bubble.remove();
              return result;
            }""")
            assert markup == {"heading": True, "item": True, "script": False, "escaped": True}
            page.locator("#chat-new").click()
            page.locator("#chat-add-menu summary").click()
            assert page.get_by_role("button", name="Adicionar arquivos").is_visible()
            assert page.get_by_role("button", name="Transcrever áudio").is_visible()
            assert page.locator(".chat-add-options").bounding_box()["y"] < page.locator("#chat-add-menu summary").bounding_box()["y"]
            page.screenshot(path="/tmp/maximus-chat-add-menu-desktop.png")
            with page.expect_file_chooser() as audio_chooser:
                page.get_by_role("button", name="Transcrever áudio").click()
            audio_chooser.value.set_files({"name": "recado.wav", "mimeType": "audio/wav", "buffer": b"RIFFfake"})
            assert not page.locator("#chat-add-menu").evaluate("element => element.open")
            page.get_by_text("Transcrição pronta. Revise o texto antes de enviar.").wait_for()
            assert page.locator("#chat-text").input_value() == "Áudio transcrito para revisão."
            assert len(sent) == 1
            page.locator("#chat-text").fill("")
            page.get_by_role("button", name="Gravar áudio").click()
            page.get_by_role("button", name="Parar gravação").wait_for()
            page.wait_for_timeout(300)
            page.get_by_role("button", name="Parar gravação").click()
            page.get_by_text("Transcrição pronta. Revise o texto antes de enviar.").wait_for()
            assert page.locator("#chat-text").input_value() == "Áudio transcrito para revisão."
            page.locator("#chat-text").fill("")
            assert page.locator("#chat-record").bounding_box()["x"] < page.locator(".chat-send").bounding_box()["x"]
            page.locator("#chat-add-menu summary").click()
            with page.expect_file_chooser() as file_chooser:
                page.get_by_role("button", name="Adicionar arquivos").click()
            file_chooser.value.set_files({"name": "notas.txt", "mimeType": "text/plain", "buffer": b"dados ficticios"})
            page.locator("#chat-files .chat-file-card strong").get_by_text("notas.txt").wait_for()
            assert page.get_by_role("button", name="Remover notas.txt").is_visible()
            with page.expect_request("**/api/chat/messages") as upload:
                page.locator("#chat-form button[type=submit]").click()
            sent_file = upload.value.post_data_json
            assert sent_file["text"] == "" and sent_file["attachments"][0]["name"] == "notas.txt"
            assert sent_file["attachments"][0]["data"] == "ZGFkb3MgZmljdGljaW9z"
            page.wait_for_function("state.chat.runs.some(run => run.attachments?.length)")
            page.locator(".chat-bubble.user .chat-file-card strong").get_by_text("notas.txt").wait_for()
            assert page.locator(".chat-bubble.user .chat-file-card .ui-icon").count() > 0
            page.get_by_role("button", name="Visualizar notas.txt").click()
            page.locator("#artifact-dialog-body pre").get_by_text("dados ficticios").wait_for()
            with page.expect_download() as downloaded:
                page.locator("#artifact-dialog-download").click()
            assert downloaded.value.suggested_filename == "notas.txt"
            page.locator("#artifact-dialog-close").click()
            assert "📎" not in page.locator("#chat-transcript").inner_text()
        else:
            page.get_by_role("heading", name="Visão de uso").wait_for()
            page.get_by_text("CONTABIL", exact=True).wait_for()
            assert not any(path.startswith("governance/runs/") for path in calls)
            page.locator("#governance-runs button").first.click()
            page.get_by_text("Esta leitura de conteúdo bruto foi registrada para auditoria.").wait_for()
            assert any(path.startswith("governance/runs/") for path in calls)
        page.screenshot(path=screenshot, full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.screenshot(path=screenshot.replace(".png", "-mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors, errors
        context.close()

    for connected_count in (0, 2):
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        def account_route(route):
            path = route.request.url.split("/api/", 1)[1]
            if path == "auth/me":
                return mock(route, {"employee_code": "COLAB001", "role": "collaborator", "must_change_password": False})
            if path == "oauth/credentials":
                return mock(route, [{"credential_id": f"CONTA{i}", "connected": True, "can_connect": True} for i in range(connected_count)])
            if path == "chat/projects":
                return mock(route, {"projects": []})
            if path.startswith("chat/history"):
                return mock(route, {"runs": []})
            if path.startswith("chat/conversations?"):
                return mock(route, {"conversations": [], "next_before": None})
            return mock(route, {}, status=404)

        page.route("**/api/**", account_route)
        page.goto(BASE)
        page.get_by_role("heading", name="Como posso ajudar hoje?").wait_for()
        page.locator(".credential-picker" if connected_count == 2 else "#chat-header-accounts").wait_for(state="visible")
        assert page.locator(".credential-picker").is_visible() == (connected_count == 2)
        assert page.locator("#chat-header-accounts").is_visible() == (connected_count == 0)
        context.close()

    context = browser.new_context(viewport={"width": 1448, "height": 900}, ignore_https_errors=True)
    page = context.new_page()
    page.add_init_script("window.open = () => null")
    sent = []

    def reconnect(route):
        request = route.request
        path = request.url.split("/api/", 1)[1]
        if path == "auth/me":
            return mock(route, {"employee_code": "COLAB001", "role": "collaborator", "must_change_password": False})
        if path == "oauth/credentials":
            return mock(route, [{"credential_id": "CONTA01", "connected": True, "can_connect": True}])
        if path == "chat/projects":
            return mock(route, {"projects": []})
        if path.startswith("chat/history"):
            return mock(route, {"runs": [] if len(sent) < 2 else [{"run_id": "11111111-1111-4111-8111-111111111111", "client_message_id": sent[0]["client_message_id"], "prompt": "Reconectar", "response": {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Reconexão concluída"}]}]}, "outcome": "completed"}]})
        if path.startswith("chat/conversations?"):
            return mock(route, {"conversations": [], "next_before": None})
        if path.endswith("/suggest-title"):
            return mock(route, {"title": None})
        if path == "chat/messages":
            sent.append(request.post_data_json)
            if len(sent) == 1:
                return mock(route, {"code": "reconnect_required", "client_message_id": sent[0]["client_message_id"]}, status=409)
            answer = {"type": "response.completed", "response": {"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Reconexão concluída"}]}]}}
            return mock(route, "event: response.completed\ndata: " + json.dumps(answer) + "\n\n", content_type="text/event-stream", headers={"X-Conversation-ID": "22222222-2222-4222-8222-222222222222"})
        if path == "oauth/credentials/CONTA01/start":
            return mock(route, {"connection_id": "22222222-2222-4222-8222-222222222222", "authorize_url": "https://example.com/authorize"})
        if path == "oauth/connections/22222222-2222-4222-8222-222222222222/complete":
            return mock(route, {"connected": True})
        return mock(route, {}, status=404)

    page.route("**/api/**", reconnect)
    page.goto(BASE)
    page.locator("#chat-text").fill("Reconectar")
    page.locator("#chat-form button[type=submit]").click()
    page.locator("#chat-reconnect-button").click()
    page.locator("#callback-url").fill("http://localhost:1455/auth/callback?code=sample")
    page.locator("#callback-form button[type=submit]").click()
    page.get_by_text("Reconexão concluída").wait_for()
    assert len(sent) == 2 and sent[0] == sent[1]
    context.close()
    browser.close()
