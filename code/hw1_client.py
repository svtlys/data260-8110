import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from model_client import ModelClient  # noqa: E402


def main():
    client = ModelClient(model="qwen3:8b", temperature=0.0)

    agent_md_path = Path(__file__).resolve().parent.parent / "AGENT.md"
    if agent_md_path.exists():
        system_prompt = agent_md_path.read_text()
        client.add_system_message(system_prompt)
        print(f"(Loaded system prompt from {agent_md_path})\n")

    print("hw1_client — type a message, '/stats' for stats, or '/exit' to quit.\n")

    while True:
        user_input = input("You: ").strip()

        if user_input == "/exit":
            break

        if user_input == "/stats":
            stats = client.stats()
            print("\n--- /stats ---")
            for k, v in stats.items():
                print(f"{k}: {v}")
            print()
            continue

        if not user_input:
            continue

        client.add_user_message(user_input)
        response = client.complete()
        print(f"Assistant: {response.content}\n")

    client.print_final_summary()


if __name__ == "__main__":
    main()