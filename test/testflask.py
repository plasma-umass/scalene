from flask import Flask

app = Flask(__name__)

cache = {}

@app.route("/<page>")
def index(page):
    if page not in cache:
        cache[page] = f"<h1>Welcome to {page}</h1>"
    return cache[page]


if __name__ == "__main__":
    app.run()
    
