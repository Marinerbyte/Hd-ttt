from flask import Flask, render_template_string, request, jsonify
import requests, os

app = Flask(__name__)

HTML = """
<h2>Master Dashboard</h2>
<form id="pluginForm">
Plugin Name: <input name="plugin" id="plugin">
<button onclick="loadPlugin()">Load Plugin</button>
</form>
<div id="result"></div>
<script>
function loadPlugin(){
    event.preventDefault();
    let plugin = document.getElementById('plugin').value;
    fetch('/api/load_plugin', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:plugin})})
    .then(r=>r.json()).then(d=>document.getElementById('result').innerText=d.result)
}
</script>
"""

@app.route("/")
def dashboard(): return render_template_string(HTML)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5001)))
