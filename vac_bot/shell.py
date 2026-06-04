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
            citations = [citation for citation in result.get("citations", []) if citation.get("used")]
            if citations:
                print("Sources:")
                for citation in citations:
                    page_number = citation.get("page_number")
                    page_label = f"page {page_number}" if page_number not in (None, "", "n/a") else "no page"
                    print(f"  [{citation.get('citation_id')}] {citation.get('source_file')} ({page_label})")
                    excerpt = citation.get("excerpt") or ""
                    if excerpt:
                        print(f"    {excerpt}")
                print()
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())