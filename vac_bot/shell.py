# vac_bot/shell.py
import asyncio
from .chain import ask

async def main():
    print("VAC FAQ Bot ready (type 'quit' to exit)\n")
    while True:
        try:
            q = input("You: ").strip()
            if q.lower() in {"quit", "exit", "q"}:
                print("Goodbye!")
                break
            if not q:
                continue
                
            result = await ask(q)
            print(f"\nVAC-Bot: {result['answer']}")
            print(f"Tokens → in:{result['input_tokens']} out:{result['output_tokens']} total:{result['total_tokens']}\n")
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())