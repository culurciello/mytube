from flask import Flask, render_template, request, jsonify, session
from youtube_transcript_api import YouTubeTranscriptApi
import re
import math

app = Flask(__name__)
app.secret_key = "mytube-secret-key"

# In-memory store: { video_id: { "title": str, "segments": [...] } }
videos_store = {}


def extract_video_id(url):
    """Extract YouTube video ID from various URL formats."""
    patterns = [
        r"(?:v=)([a-zA-Z0-9_-]{11})",
        r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})",
        r"(?:embed/)([a-zA-Z0-9_-]{11})",
        r"(?:shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def get_thumbnail(video_id):
    return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"


def fetch_transcript(video_id):
    """Fetch transcript and group into ~30-second segments."""
    transcript_data = YouTubeTranscriptApi().fetch(video_id)

    segments = []
    current_segment = {"start": 0, "text": "", "entries": []}
    segment_duration = 30  # seconds per segment

    for entry in transcript_data.snippets:
        segment_index = int(entry.start // segment_duration)
        expected_start = segment_index * segment_duration

        if expected_start != current_segment["start"] and current_segment["text"]:
            segments.append(current_segment)
            current_segment = {"start": expected_start, "text": "", "entries": []}

        current_segment["start"] = expected_start
        current_segment["text"] += " " + entry.text
        current_segment["entries"].append(entry)

    if current_segment["text"]:
        segments.append(current_segment)

    for seg in segments:
        seg["text"] = seg["text"].strip()

    return segments


def format_time(seconds):
    """Convert seconds to mm:ss format."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def search_segments(segments, query, top_n=5):
    """Rank segments by simple TF-based relevance to the query."""
    query_terms = query.lower().split()
    scored = []

    for i, seg in enumerate(segments):
        text_lower = seg["text"].lower()
        score = 0
        for term in query_terms:
            score += text_lower.count(term)
        if score > 0:
            scored.append({
                "index": i,
                "start": seg["start"],
                "time": format_time(seg["start"]),
                "text": seg["text"],
                "score": score,
            })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/load", methods=["POST"])
def load_video():
    data = request.get_json()
    url = data.get("url", "").strip()
    video_id = extract_video_id(url)

    if not video_id:
        return jsonify({"error": "Invalid YouTube URL"}), 400

    if video_id in videos_store:
        count = len(videos_store[video_id]["segments"])
        return jsonify({
            "video_id": video_id,
            "thumbnail": get_thumbnail(video_id),
            "segment_count": count,
            "message": f"Transcript loaded ({count} segments)",
        })

    try:
        segments = fetch_transcript(video_id)
    except Exception as e:
        return jsonify({"error": f"Could not fetch transcript: {str(e)}"}), 400

    videos_store[video_id] = {"segments": segments}

    return jsonify({
        "video_id": video_id,
        "thumbnail": get_thumbnail(video_id),
        "segment_count": len(segments),
        "message": f"Transcript loaded ({len(segments)} segments)",
    })


@app.route("/search", methods=["POST"])
def search():
    data = request.get_json()
    video_id = data.get("video_id", "").strip()
    query = data.get("query", "").strip()

    if not video_id or video_id not in videos_store:
        return jsonify({"error": "Load a video first"}), 400
    if not query:
        return jsonify({"error": "Enter a search query"}), 400

    segments = videos_store[video_id]["segments"]
    results = search_segments(segments, query)

    if not results:
        return jsonify({"results": [], "message": "No matches found"})

    for r in results:
        r["thumbnail"] = get_thumbnail(video_id)
        r["video_id"] = video_id

    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(debug=True, port=5173)
