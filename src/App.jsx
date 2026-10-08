import { useEffect, useState } from 'react'
import './App.css'

const N8N_WEBHOOK_URL = 'http://localhost:8000/api/ai-chat'

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
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setSessionId(getSessionId())
  }, [])

  function startNewConversation() {
    const newSessionId = crypto.randomUUID()

    localStorage.setItem('ai-chat-session-id', newSessionId)

    setSessionId(newSessionId)
    setMessages([])
    setError('')
    setInput('')
  }

  async function sendMessage(event) {
    event.preventDefault()

    const message = input.trim()

    if (!message || loading || !sessionId) {
      return
    }

    setError('')

    const userMessage = {
      role: 'user',
      content: message,
    }

    setMessages((currentMessages) => [
      ...currentMessages,
      userMessage,
    ])

    setInput('')
    setLoading(true)

    try {
      const response = await fetch(N8N_WEBHOOK_URL, {
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

        throw new Error(`Request failed with status ${response.status}`)
      }

      const data = await response.json()

      const assistantMessage = {
        role: 'assistant',
        content:
          data.output ||
          data.text ||
          'I received an empty response from the AI assistant.',
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        assistantMessage,
      ])
    } catch (err) {
      console.error('Chat request failed:', err)

      setError(
        "I couldn't reach the AI assistant. Make sure n8n is running and the workflow is published."
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
            <h1>AI Business Assistant</h1>
            <p>Powered by n8n + Gemini</p>
          </div>

          <button
            type="button"
            onClick={startNewConversation}
            disabled={loading}
          >
            New Conversation
          </button>
        </header>

        <main className="messages">
          {messages.length === 0 && (
            <div className="welcome">
              <h2>Hello 👋</h2>
              <p>
                Ask me anything to start the conversation.
              </p>
            </div>
          )}

          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={`message-row ${message.role}`}
            >
              <div className="message">
                {message.content}
              </div>
            </div>
          ))}

          {loading && (
            <div className="message-row assistant">
              <div className="message typing">
                Thinking...
              </div>
            </div>
          )}
        </main>

        {error && (
          <div className="error">
            {error}
          </div>
        )}

        <form className="composer" onSubmit={sendMessage}>
          <input
            type="text"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Type your message..."
            disabled={loading}
          />

          <button
            type="submit"
            disabled={
              loading ||
              !input.trim() ||
              !sessionId
            }
          >
            Send
          </button>
        </form>
      </div>
    </div>
  )
}

export default App
