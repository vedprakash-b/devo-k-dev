"""An offline demonstration of the router, with scripted providers and a fake clock.

``devokdev models demo`` runs this. It needs no API keys and no network, so anyone can see
the router's behaviour in a few seconds, and the unit tests run it too, so it never breaks.

The story, using the real registry:

1. The best model for the Backend Engineer asks to run a tool.
2. With the tool's result, the conversation continues; the model returns HTTP 429.
   The router benches it for the retry-after and hands the whole conversation, tool call
   included, to the next model, which answers.
3. A follow-up stays on the new model: sessions are sticky.
4. Two and a half minutes later, the cooldown is over and the session switches back.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import SecretStr

from devokdev.config import PROVIDER_KEY_FIELDS, Settings
from devokdev.llm.messages import CompletionRequest, Message, ToolSpec
from devokdev.llm.registry import Registry
from devokdev.llm.scripted import Reply, ScriptedTransport
from devokdev.router.factory import open_router
from devokdev.router.policy import RouteRequest
from devokdev.router.router import RoutedResult

LIST_DIR = ToolSpec(
    name="list_dir",
    description="List the files in a directory of the project.",
    parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
)


@dataclass
class DemoClock:
    now: float = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class DemoTurn:
    title: str
    prompt: str
    routed: RoutedResult
    note: str = ""


@dataclass
class DemoRun:
    first: str
    second: str
    turns: list[DemoTurn] = field(default_factory=list)


def demo_settings(base: Settings) -> Settings:
    """Fake keys for every provider, so the whole registry is in play. Nothing is sent."""
    keys = {name: SecretStr("demo-key") for name in PROVIDER_KEY_FIELDS}
    return Settings(
        _env_file=None,
        models_file=base.models_file,
        cloudflare_account_id="demo",
        router_switch_back_after_s=120,
        **keys,  # type: ignore[arg-type]
    )


async def run_demo(
    registry: Registry, settings: Settings, on_turn: Callable[[DemoTurn], None] = lambda _t: None
) -> DemoRun:
    demo = demo_settings(settings)
    clock = DemoClock()
    transport = ScriptedTransport()
    async with open_router(
        demo,
        registry=registry,
        transport=transport,
        use_redis=False,
        clock=clock,
        sleep=clock.sleep,
    ) as ctx:
        plan = await ctx.router.plan(
            RouteRequest(role="backend", est_input_tokens=200, max_output_tokens=1024)
        )
        if len(plan.candidates) < 2:
            raise RuntimeError("the demo needs at least two models that can play backend")
        first, second = plan.candidates[0].model, plan.candidates[1].model
        host = {
            m.id: (registry.base_url(registry.provider_of(m), demo) or "").split("/")[2]
            for m in (first, second)
        }
        transport.add(
            f"{host[first.id]}/{first.name}",
            Reply(tool_calls=(("list_dir", {"path": "src/devokdev"}),), usage=(180, 24)),
            Reply.rate_limited(retry_after_s=30),
            Reply(
                text="Back on the first model: llm/ talks to providers, router/ picks them.",
                usage=(420, 22),
            ),
        )
        transport.add(
            f"{host[second.id]}/{second.name}",
            Reply(
                text="src/devokdev has llm/, router/, fitness/ and the CLI. "
                "The router lives in router/.",
                usage=(260, 31),
            ),
            Reply(
                text="router/policy.py ranks the models; router/router.py runs the fallbacks.",
                usage=(340, 19),
            ),
        )
        run = DemoRun(first.id, second.id)
        session = ctx.router.session("backend")
        system = Message.system("You are the Backend Engineer on Devo-K-Dev.")
        question = Message.user("What is in src/devokdev?")

        async def turn(
            title: str, prompt: str, request: CompletionRequest, note: str = ""
        ) -> RoutedResult:
            routed = await session.complete(request)
            item = DemoTurn(title, prompt, routed, note)
            run.turns.append(item)
            on_turn(item)
            return routed

        conversation = CompletionRequest(messages=(system, question), tools=(LIST_DIR,))
        one = await turn(
            "1. The best model asks to run a tool", question.content or "", conversation
        )
        call = one.result.message.tool_calls[0]
        conversation = conversation.appended(
            one.result.message, Message.tool_result(call, "llm/  router/  fitness/  cli.py")
        )
        await turn(
            "2. Mid-task, that model is rate limited",
            "(tool result: llm/  router/  fitness/  cli.py)",
            conversation,
            note="The next model received the whole conversation: "
            "system, user, the tool call and its result.",
        )
        conversation = conversation.appended(
            run.turns[-1].routed.result.message, Message.user("Where does model ranking happen?")
        )
        await turn(
            "3. A follow-up stays on the same model",
            "Where does model ranking happen?",
            conversation,
        )
        clock.now += 150
        conversation = conversation.appended(
            run.turns[-1].routed.result.message, Message.user("Summarise in one line.")
        )
        await turn(
            "4. Two and a half minutes later, the session switches back",
            "Summarise in one line.",
            conversation,
        )
    return run
