import asyncio
from typing import Awaitable, Sequence


async def run_concurrently_with_limit[T](
    coroutines: Sequence[Awaitable[T]], limit: int
) -> tuple[list[T], list[BaseException]]:
    semaphore = asyncio.Semaphore(limit)
    tasks = []

    async def run_task(coro: Awaitable[T]) -> T:
        async with semaphore:
            return await coro

    for coro in coroutines:
        tasks.append(run_task(coro))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    successes = [result for result in results if not isinstance(result, BaseException)]
    errors = [result for result in results if isinstance(result, BaseException)]

    return successes, errors
