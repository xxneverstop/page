import json

from scripts.watch_trace import format_event, read_events


def test_format_event_shows_decoded_chinese_tool_result():
    # trace 文件使用 Unicode 转义，查看器应显示解码后的工具结果。
    event = json.loads(
        r'{"event":"tool_executed","name":"read_file","result":"\u8bfb\u53d6\u6210\u529f"}'
    )

    output = format_event(event, detail=True)

    assert "read_file" in output
    assert "读取成功" in output
    assert r"\u8bfb" not in output


def test_read_events_waits_for_complete_line_without_repeating_output(tmp_path, capsys):
    trace_path = tmp_path / "trace.jsonl"
    first_line = (
        json.dumps({"event": "tool_executed", "name": "read_file", "result": "中文结果"}) + "\n"
    ).encode("utf-8")
    final_line = (
        json.dumps(
            {"event": "run_finished", "status": "completed", "final_answer": "完成"},
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    # 写入中的最后一行必须留到补齐换行符后再消费。
    trace_path.write_bytes(first_line + final_line[:-1])

    offset, finished = read_events(trace_path, 0, detail=True)

    assert offset == len(first_line)
    assert finished is False
    output = capsys.readouterr().out
    assert output.count("中文结果") == 1
    assert "run_finished" not in output
    assert r"\u4e2d" not in output

    assert read_events(trace_path, offset, detail=True) == (offset, False)
    assert capsys.readouterr().out == ""

    with trace_path.open("ab") as handle:
        handle.write(b"\n")

    offset, finished = read_events(trace_path, offset, detail=True)

    assert offset == trace_path.stat().st_size
    assert finished is True
    output = capsys.readouterr().out
    assert "run_finished" in output
    assert "完成" in output
    assert "中文结果" not in output

    next_offset, _ = read_events(trace_path, offset, detail=True)
    assert next_offset == offset
    assert capsys.readouterr().out == ""


def test_verbose_events_show_full_multiline_request_prompt_and_adapter_text():
    full_text = "第一行\n" + "完整内容" * 1500 + "\n最后一行"
    request = format_event({
        "event": "run_started", "full_request": True, "user_request": full_text,
    })
    prompt = format_event({
        "event": "prompt_rendered", "attempts": 2, "tool_protocol": "text",
        "section_order": ["prefix", "current_request"],
        "sections": {
            "prefix": {"raw_chars": 100, "rendered_chars": 90},
            "current_request": {"raw_chars": len(full_text), "rendered_chars": len(full_text)},
        },
        "prompt": full_text,
    })
    extracted = format_event({"event": "model_extracted", "format": "text", "text": full_text})

    # 默认模式必须保留详细采集的全部文本，而不只打印预览或压平换行。
    for output in (request, prompt, extracted):
        assert "第一行\n" in output
        assert "完整内容" * 1500 in output
        assert "\n    最后一行" in output
    assert "[prefix]：100 → 90" in prompt
    assert "[current_request]" in prompt
    assert "【适配器返回】" in extracted


def test_verbose_http_events_show_complete_body_and_preserve_sse_lines():
    long_value = "中文请求" * 500
    request = format_event({
        "event": "model_http_request", "attempt": 1,
        "url": "https://example.test/v1/messages",
        "body": {"model": "example-model", "messages": [{"content": long_value}]},
    })
    response_body = 'event: content_block_delta\ndata: {"text":"你好"}\n\ndata: [DONE]\n'
    response = format_event({
        "event": "model_http_response", "attempt": 1, "status": 200,
        "url": "https://example.test/v1/messages", "body": response_body,
    })
    decoded_json = format_event({
        "event": "model_http_response", "status": 200,
        "body": json.dumps({"text": "你好"}),
    })
    error = format_event({
        "event": "model_http_error", "attempt": 2,
        "url": "https://example.test/v1/messages", "error": "连接中断\n请稍后重试",
    })

    assert long_value in request
    assert "messages" in request
    assert r"\u4e2d" not in request
    assert "HTTP 200" in response
    assert 'event: content_block_delta\n    data: {"text":"你好"}' in response
    assert "data: [DONE]" in response
    assert '"text": "你好"' in decoded_json
    assert "连接中断\n    请稍后重试" in error


def test_verbose_model_decision_is_distinct_from_extraction_even_for_empty_payload():
    tool = {"name": "read_file", "args": {"path": "中文目录/文件.py", "start": 1, "end": 3}}
    extracted = format_event({"event": "model_extracted", "format": "native", "text": "", "tool_calls": [tool]})
    decision = format_event({"event": "model_parsed", "kind": "tool", "tool_name": "read_file", "payload": tool})

    assert "【适配器返回】" in extracted
    assert "原生工具调用" in extracted
    assert "中文目录/文件.py" in extracted
    assert "【操作判定】" in decision
    assert "中文目录/文件.py" in decision
    assert "【操作判定】" in format_event({"event": "model_parsed", "kind": "retry", "payload": ""})
    assert "【模型响应】" in format_event({"event": "model_parsed", "kind": "final"})


def test_verbose_tool_events_show_approval_before_execution_and_full_return():
    requested = format_event({
        "event": "tool_requested", "name": "run_shell", "args": {"command": "python -m pytest"}, "call_id": "call-1",
    })
    approval = format_event({
        "event": "tool_stage", "name": "run_shell", "stage": "approval_requested", "approval": "ask",
    })
    executing = format_event({"event": "tool_stage", "name": "run_shell", "stage": "executing"})
    result = "第一行\n" + "工具输出" * 300 + "\n完成"
    returned = format_event({"event": "tool_executed", "name": "run_shell", "tool_status": "ok", "verbose": True, "result": result})

    assert "进入工具执行器" in requested
    assert "python -m pytest" in requested
    assert "调用 call-1" in requested
    assert "等待人工审批" in approval
    assert "开始执行" in executing
    assert "工具返回内容" in returned
    assert "工具输出" * 300 in returned
    assert "│ 完成" in returned
    assert "结果预览" not in returned


def test_detail_mode_keeps_full_event_fields_for_verbose_events():
    event = {"event": "model_extracted", "format": "text", "text": "第一行\n第二行", "tool_calls": []}

    output = format_event(event, detail=True)

    assert '"event": "model_extracted"' in output
    assert '"tool_calls": []' in output
    assert "第一行" in output
    assert r"\u7b2c" not in output
