import { useState } from 'react'
import './App.css'

const AI_CHAT_API_URL = 'http://localhost:8000/api/ai-chat'

function getSessionId() {
  const existingSessionId = localStorage.getItem('ai-chat-session-id')

  if (existingSessionId) {
    return existingSessionId
  }

  const newSessionId = crypto.randomUUID()
  localStorage.setItem('ai-chat-session-id', newSessionId)

  return newSessionId
}

function App() {
  const [sessionId, setSessionId] = useState(() => getSessionId())
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [listening, setListening] = useState(false)
  const [error, setError] = useState('')

  function startNewConversation() {
    const newSessionId = crypto.randomUUID()

    localStorage.setItem('ai-chat-session-id', newSessionId)

    setSessionId(newSessionId)
    setMessages([])
    setError('')
    setInput('')

    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
  }

  function startVoiceInput() {
    if (loading || listening || !sessionId) {
      return
    }

    setError('')

    const SpeechRecognitionConstructor =
      window.SpeechRecognition || window.webkitSpeechRecognition

    if (!SpeechRecognitionConstructor) {
      setError(
        'Speech recognition is not supported by this browser. Try a recent version of Chrome or Edge.'
      )
      return
    }

    const recognition = new SpeechRecognitionConstructor()

    recognition.lang = 'en-US'
    recognition.continuous = false
    recognition.interimResults = false
    recognition.maxAlternatives = 1

    recognition.onstart = () => {
      setListening(true)
    }

    recognition.onresult = (event) => {
      const transcript = event.results?.[0]?.[0]?.transcript?.trim()

      if (!transcript) {
        setError('No speech was detected. Please try again.')
        return
      }

      setInput(transcript)

      // Voice questions are submitted automatically after recognition.
      void sendMessage(null, transcript, true)
    }

    recognition.onerror = (event) => {
      const speechErrors = {
        'not-allowed':
          'Microphone access was denied. Allow microphone access in your browser settings.',
        'service-not-allowed':
          'The browser speech recognition service is unavailable.',
        'no-speech':
          'No speech was detected. Click the microphone and try again.',
        'audio-capture':
          'No microphone was found. Check your microphone connection.',
        network:
          'Speech recognition needs an internet connection in this browser.',
      }

      setError(
        speechErrors[event.error] ||
          `Speech recognition failed (${event.error}). Please try again.`
      )
    }

    recognition.onend = () => {
      setListening(false)
    }

    try {
      recognition.start()
    } catch (err) {
      console.error('Could not start speech recognition:', err)
      setListening(false)
      setError('Could not start the microphone. Please try again.')
    }
  }

  async function sendMessage(event, overrideMessage = null, speakResponse = false) {
    if (event && typeof event.preventDefault === 'function') {
      event.preventDefault()
    }

    const message = (
      typeof overrideMessage === 'string' ? overrideMessage : input
    ).trim()

    if (!message || loading || !sessionId) {
      return
    }

    setError('')

    setMessages((currentMessages) => [
      ...currentMessages,
      { role: 'user', content: message },
    ])

    setInput('')
    setLoading(true)

    try {
      const response = await fetch(AI_CHAT_API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          sessionId,
          message,
        }),
      })

      if (!response.ok) {
        if (response.status === 429) {
          setError(
            'You have sent too many messages in a short period. Please wait a minute and try again.'
          )
          return
        }

        if (response.status === 503) {
          const retryAfter = Number(response.headers.get('Retry-After'))

          setError(
            Number.isFinite(retryAfter) && retryAfter > 0
              ? `The assistant is busy right now. Please try again in ${retryAfter} seconds.`
              : 'The assistant is busy right now. Please try again shortly.'
          )
          return
        }

        throw new Error(`Request failed with status ${response.status}`)
      }

      const data = await response.json()

      const answer =
        data.output ||
        data.text ||
        'I received an empty response from the AI assistant.'

      setMessages((currentMessages) => [
        ...currentMessages,
        { role: 'assistant', content: answer },
      ])

      // Speak the reply only when the question came through voice.
      if (speakResponse) {
        if (
          'speechSynthesis' in window &&
          'SpeechSynthesisUtterance' in window
        ) {
          window.speechSynthesis.cancel()

          const utterance = new SpeechSynthesisUtterance(answer)
          utterance.lang = 'en-US'

          window.speechSynthesis.speak(utterance)
        } else {
          setError('Speech playback is not supported by this browser.')
        }
      }
    } catch (err) {
      console.error('Chat request failed:', err)

      setError(
        "I couldn't reach the AI assistant. Make sure FastAPI and n8n are running and the AI workflow is active."
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app">
      <div className="chat-container">
        <header className="chat-header">
          <div>
            <h1>BlueOrbit AI Assistant</h1>
            <p>Powered by FastAPI, n8n and Gemini</p>
          </div>

          <button
            type="button"
            onClick={startNewConversation}
            disabled={loading || listening}
          >
            New Conversation
          </button>
        </header>

        <main className="messages" aria-live="polite">
          {messages.length === 0 && (
            <div className="welcome">
              <h2>Hello!</h2>
              <p>Ask a question by typing or using your microphone.</p>
            </div>
          )}

          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={`message-row ${message.role}`}
            >
              <div className="message">{message.content}</div>
            </div>
          ))}

          {loading && (
            <div className="message-row assistant">
              <div className="message typing">Thinking...</div>
            </div>
          )}
        </main>

        {listening && (
          <p className="voice-status" role="status">
            Listening... Speak your question. It will be sent automatically.
          </p>
        )}

        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}

        <form className="composer" onSubmit={sendMessage}>
          <button
            type="button"
            onClick={startVoiceInput}
            disabled={loading || listening || !sessionId}
            aria-label="Ask a question using your microphone"
          >
            {listening ? 'Listening...' : '🎙 Talk'}
          </button>

          <input
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Type your message..."
            disabled={loading || listening}
          />

          <button
            type="submit"
            disabled={loading || listening || !input.trim() || !sessionId}
          >
            Send
          </button>
        </form>

        <p className="voice-note">
          Voice input uses your browser's speech recognition. Depending on
          your browser, audio may be processed by an online service.
        </p>
      </div>
    </div>
  )
}

export default App
