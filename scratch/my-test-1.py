from pathlib import Path


def demo_context_budget():
    """手动构造一个长历史，看裁剪效果"""
    from page.context_manager import ContextManager
    from page import Page, FakeModelClient
    from page.workspace import WorkspaceContext
    from page.session_store import SessionStore
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        # 构造一个有很多轮历史的 agent
        agent = Page(
            model_client=FakeModelClient([]),
            workspace=WorkspaceContext.build(Path(tmp)),
            session_store=SessionStore(Path(tmp) / ".page" / "sessions"),
        )
        # 手动往 history 里塞大量数据
        for i in range(50):
            agent.record({"role": "user", "content": f"Question {i}: " + "x" * 200})
            agent.record({"role": "assistant", "content": "y" * 500})

        cm = ContextManager(agent)
        prompt, meta = cm.build("Current request: find the bug")
        print(f"Prompt length: {len(prompt)}")
        print(f"Meta: {meta}")



if __name__ == '__main__':
    demo_context_budget()