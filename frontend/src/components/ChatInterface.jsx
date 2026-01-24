import React, { useState, useRef, useEffect } from 'react'
import axios from 'axios'
import './ChatInterface.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function ChatInterface({ onDocumentChange }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [file, setFile] = useState(null)
  const [streamingMessage, setStreamingMessage] = useState('')
  const messagesEndRef = useRef(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingMessage])

  const handleSend = async () => {
    if (!input.trim()) return

    const userMessage = { role: 'user', content: input }
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setLoading(true)

    const startTime = Date.now()

    try {
      await handleStreamingQuery(input, startTime)
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'error',
        content: 'Error: ' + (error.response?.data?.detail || error.message)
      }])
    } finally {
      setLoading(false)
    }
  }

  const handleStreamingQuery = async (query, startTime) => {
    try {
      const response = await fetch(`${API_URL}/api/query-stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query })
      })

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      let streamedAnswer = ''
      let sources = []
      let metadata = {}

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value)
        const lines = chunk.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              
              if (data.type === 'answer_chunk') {
                streamedAnswer += data.content
                setStreamingMessage(streamedAnswer)
              } else if (data.type === 'metadata') {
                sources = data.content.sources
                metadata = data.content
              }
            } catch (e) {
              console.error('Parse error:', e)
            }
          }
        }
      }

      const responseTime = Date.now() - startTime

      const botMessage = {
        role: 'assistant',
        content: streamedAnswer,
        sources: sources,
        responseTime: responseTime,
        metadata: metadata
      }

      setMessages(prev => [...prev, botMessage])
      setStreamingMessage('')
    } catch (error) {
      setMessages(prev => [...prev, {
        role: 'error',
        content: 'Error: ' + (error.message || 'Streaming failed')
      }])
    }
  }

  const handleUpload = async () => {
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    try {
      setLoading(true)
      const response = await axios.post(`${API_URL}/api/upload`, formData)
      alert(`Document "${file.name}" uploaded and indexed!\n${response.data.chunks} chunks created.`)
      setFile(null)
      if (onDocumentChange) onDocumentChange()
    } catch (error) {
      alert('Upload failed: ' + (error.response?.data?.detail || error.message))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="chat-interface">
      <div className="chat-controls">
        <div className="control-group">
          <input
            type="file"
            accept=".pdf"
            onChange={(e) => setFile(e.target.files[0])}
            disabled={loading}
          />
          <button onClick={handleUpload} disabled={!file || loading}>
            📤 Upload & Index PDF
          </button>
        </div>
      </div>

      <div className="chat-messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            <div className="message-content">{msg.content}</div>
            
            {msg.corrected && (
              <div className="correction-badge">
                ✅ Self-corrected after {msg.attempts} attempt(s)
              </div>
            )}
            
            {msg.retrievalScore !== undefined && (
              <div className="score-badge">
                🎯 Retrieval Score: {(msg.retrievalScore * 100).toFixed(1)}%
              </div>
            )}
            
            {msg.responseTime && (
              <div className="time-badge">
                ⏱️ {msg.responseTime.toFixed(0)}ms
              </div>
            )}
            
            {msg.metadata && msg.metadata.query_analysis && (
              <div className="metadata-badge">
                🔍 Type: {msg.metadata.query_analysis.type} | 
                Complexity: {msg.metadata.query_analysis.complexity}
              </div>
            )}
            
            {msg.sources && msg.sources.length > 0 && (
              <details className="sources">
                <summary>📚 Sources ({msg.sources.length})</summary>
                {msg.sources.map((src, i) => (
                  <div key={i} className="source">
                    <strong>Source {i + 1}:</strong>
                    <p>{src.substring(0, 300)}...</p>
                  </div>
                ))}
              </details>
            )}
          </div>
        ))}
        
        {streamingMessage && (
          <div className="message assistant streaming">
            <div className="message-content">{streamingMessage}</div>
            <div className="typing-indicator">▊</div>
          </div>
        )}
        
        {loading && !streamingMessage && (
          <div className="message assistant loading">
            <div className="loading-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
            <span>Thinking...</span>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyPress={(e) => e.key === 'Enter' && !loading && handleSend()}
          placeholder="Ask a question about your documents..."
          disabled={loading}
        />
        <button onClick={handleSend} disabled={loading || !input.trim()}>
          {loading ? '⏳' : '📤'} Send
        </button>
      </div>
    </div>
  )
}

export default ChatInterface