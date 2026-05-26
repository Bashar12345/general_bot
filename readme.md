# ANY Python file 
from vac_bot import ask
import asyncio

# Ask the bot
result = asyncio.run(ask("How much is 70% VA disability?", "user123"))
print(result["answer"])