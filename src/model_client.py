
import json
from langchain_ollama import ChatOllama

class ModelClient:
    def __init__(self, model: str = "qwen3:8b", temperature: float = 0.0):
        self.model_name = model
        self._llm = ChatOllama(model=model, temperature=temperature)

        self.cumulative_input_tokens = 0
        self.cumulative_output_tokens = 0
        self.turn_count = 0

        self._history = []

    def complete(self, messages=None, tools=None):
        if messages is not None:
            self._history.extend(messages)

        formatted = [(m["role"], m["content"]) for m in self._history]
        response = self._llm.invoke(formatted)

        self._history.append({"role": "assistant", "content": response.content})

        usage = getattr(response, "usage_metadata", None) or {}
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        total_tokens = input_tokens + output_tokens

        self.cumulative_input_tokens += input_tokens
        self.cumulative_output_tokens += output_tokens
        self.turn_count += 1

        print(f"[turn {self.turn_count}] input_tokens={input_tokens} "
              f"output_tokens={output_tokens} total_tokens={total_tokens}")

        return response

    def add_system_message(self, content: str):
        self._history.insert(0, {"role": "system", "content": content})

    def add_user_message(self, content: str):
        self._history.append({"role": "user", "content": content})

    def stats(self):
        history_json = json.dumps(self._history)
        return {
            "turn_count": self.turn_count,
            "cumulative_input_tokens": self.cumulative_input_tokens,
            "cumulative_output_tokens": self.cumulative_output_tokens,
            "cumulative_total_tokens": self.cumulative_input_tokens + self.cumulative_output_tokens,
            "history_length_chars": len(history_json),
        }

    def print_final_summary(self):
        print("\n=== Final cumulative stats ===")
        print(f"Total turns: {self.turn_count}")
        print(f"Cumulative input tokens: {self.cumulative_input_tokens}")
        print(f"Cumulative output tokens: {self.cumulative_output_tokens}")
        print(f"Cumulative total tokens: {self.cumulative_input_tokens + self.cumulative_output_tokens}")