from core.config import load_config


def main() -> None:
    try:
        config = load_config()
        print(f"Anthropic key: {config.anthropic_api_key}")
        print(f"OpenAI key: {config.openai_api_key}")
        print(f"Gemini key: {config.gemini_api_key}")
        print(f"OpenRouter key: {config.openrouter_api_key}")
        print("RunConfig attributes verified successfully.")
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}")


if __name__ == "__main__":
    main()
