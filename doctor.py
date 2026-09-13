"""Setup checker. Run `python doctor.py` to confirm the app will work.

Verifies the local pipeline (which needs no cloud), then reports whether an
optional generative provider is configured. Nothing here requires an API key.
"""
import os

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass


def main() -> None:
    print("FestivalScout — setup check\n" + "-" * 32)

    from constraints import load_festivals

    festivals = load_festivals()
    print(f"[ok] festival dataset loaded: {len(festivals)} festivals")

    from retrieval import get_retriever

    r = get_retriever()
    print(f"[ok] retrieval index built: backend={r.backend}, chunks={len(r.chunks)}")
    hits = r.search("horror feature premiere deadline", k=3)
    print(f"[ok] retrieval query returned {len(hits)} cited passages "
          f"(top: {hits[0].festival_name})")

    provider = os.getenv("LLM_PROVIDER", "none").lower()
    if provider == "none":
        print("[info] LLM_PROVIDER=none -> analysis is composed locally (no API key needed).")
    elif provider == "openai":
        ok = bool(os.getenv("OPENAI_API_KEY"))
        print(f"[{'ok' if ok else 'warn'}] LLM_PROVIDER=openai; "
              f"OPENAI_API_KEY {'set' if ok else 'MISSING — will fall back to local'}.")
    elif provider == "azure":
        ok = bool(os.getenv("AZURE_OPENAI_ENDPOINT") and
                  (os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("FOUNDRY_API_KEY")))
        print(f"[{'ok' if ok else 'warn'}] LLM_PROVIDER=azure; "
              f"credentials {'set' if ok else 'MISSING — will fall back to local'}.")
    else:
        print(f"[warn] unknown LLM_PROVIDER={provider!r}; will fall back to local synthesis.")

    print("\nAll core checks passed. Start the app with:  uvicorn main:app --reload")


if __name__ == "__main__":
    main()
