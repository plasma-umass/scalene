import uvicorn

async def app(scope, receive, send):
    assert scope['type'] == 'http'

    await send({
        'type': 'http.response.start',
        'status': 200,
        'headers': [
            [b'content-type', b'text/plain'],
        ],
    })
    await send({
        'type': 'http.response.body',
        'body': b'Hello, world!',
    })

if __name__ == "__main__":
    # NOTE: different name scheme because uvicorn seems to
    # import things based on names, and the test-issue\d+ 
    # doesn't make a valid name
    uvicorn.run("issue270:app", 
                host="0.0.0.0",
                port=8080,
                workers=2,
                limit_concurrency=40,
                backlog=300)