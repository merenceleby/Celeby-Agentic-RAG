import React, { useState, useRef, useEffect, useCallback } from 'react'
import axios from 'axios'
import './ChatInterface.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function ChatInterface({
  onDocumentChange,
  conversationId,
  onConversationCreated,
  onConversationActivity
}) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [file, setFile] = useState(null)
  const [streamingMessage, setStreamingMessage] = useState('')
  const [mode, setMode] = useState('quality')
  const messagesEndRef = useRef(null)

  const MODE_DESCRIPTIONS = {
    fast: '⚡ Blazing fast streaming RAG with lighter reasoning.',
    quality: '🎯 Multi-query rewriting, validation and self-correction for maximum accuracy.',
    direct: '💬 Bypass documents entirely and talk straight to the base LLM.'
  }

  const normalizeSources = (sources) => {
    if (!sources) return []
    if (Array.isArray(sources)) return sources
    if (typeof sources === 'string') return [sources]
    try {
      const parsed = JSON.parse(sources)
      return Array.isArray(parsed) ? parsed : [parsed]
    } catch {
      return [sources]
    }
  }

  const asSourceText = (src) => {
    if (!src) return ''
    if (typeof src === 'string') return src
    if (typeof src.text === 'string') return src.text
    if (typeof src.content === 'string') return src.content
    try {
      return JSON.stringify(src)
    } catch {
      return String(src)
    }
  }

  const parseMetadata = (raw) => {
    if (!raw) return {}
    if (typeof raw === 'string') {
      try {
        return JSON.parse(raw)
      } catch {
        return {}
      }
    }
    return raw
  }

  const mapHistoryMessage = useCallback(
    (msg) => {
      const metadata = parseMetadata(msg.metadata)
      return {
        id: msg.id,
        role: msg.role === 'assistant' ? 'assistant' : 'user',
        content: msg.content,
        sources: normalizeSources(metadata.sources),
        retrievalScore: metadata.retrieval_score,
        responseTime: metadata.response_time_ms,
        corrected: metadata.was_corrected,
        attempts: metadata.correction_attempts,
        metadata,
        userFeedback: null,
        createdAt: msg.created_at
      }
    },
    []
  )

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    if (!conversationId) {
      setMessages([])
      setStreamingMessage('')
      setHistoryLoading(false)
      return
    }

    const loadHistory = async () => {
      try {
        setHistoryLoading(true)
        const response = await axios.get(
          `${API_URL}/api/conversations/${conversationId}/messages`
        )
        const history = (response.data.messages || []).map(mapHistoryMessage)
        setMessages(history)
      } catch (error) {
        console.error('Failed to load conversation history:', error)
      } finally {
        setHistoryLoading(false)
      }
    }

    loadHistory()
  }, [conversationId, mapHistoryMessage])

  useEffect(() => {
    scrollToBottom()
  }, [messages, streamingMessage])

  const handleSend = async () => {
    const question = input.trim()
    if (!question) return

    const userMessage = {
      role: 'user',
      content: question,
      timestamp: Date.now(),
      metadata: { mode }
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setLoading(true)

    try {
      await handleStreamingQuery(question, Date.now())
    } catch (error) {
      setStreamingMessage('')
      setMessages((prev) => [
        ...prev,
        {
          role: 'error',
          content: 'Error: ' + (error.response?.data?.detail || error.message)
        }
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleStreamingQuery = async (query, startTime) => {
    let streamedAnswer = ''
    let metadata = {}
    let resolvedConversationId = conversationId
    let notifiedConversation = false
    let buffer = ''

    const processEvent = (eventChunk) => {
      if (!eventChunk.startsWith('data: ')) return
      const payload = eventChunk.slice(6)
      if (!payload) return

      let data
      try {
        data = JSON.parse(payload)
      } catch (error) {
        console.error('Stream parse error:', error)
        return
      }

      if (data.type === 'conversation') {
        const newId = data.content?.conversation_id
        if (newId) {
          resolvedConversationId = newId
          if (!notifiedConversation && onConversationCreated) {
            onConversationCreated(newId)
            notifiedConversation = true
          }
        }
      } else if (data.type === 'answer_chunk') {
        streamedAnswer += data.content
        setStreamingMessage(streamedAnswer)
      } else if (data.type === 'metadata') {
        metadata = data.content || {}
        setStreamingMessage('')
      } else if (data.type === 'answer' && data.done) {
        streamedAnswer = data.content
        setStreamingMessage(streamedAnswer)
      } else if (data.type === 'error') {
        throw new Error(data.content || 'Streaming error')
      }
    }

    const response = await fetch(`${API_URL}/api/query-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        conversation_id: resolvedConversationId,
        mode
      })
    })

    if (!response.body) {
      throw new Error('Streaming not supported by server response')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()

    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const chunk = buffer.slice(0, boundary).trim()
        buffer = buffer.slice(boundary + 2)
        if (chunk) processEvent(chunk)
        boundary = buffer.indexOf('\n\n')
      }
    }

    if (buffer.trim()) {
      processEvent(buffer.trim())
    }

    const responseTime = metadata.response_time_ms || (Date.now() - startTime)
    const answerContent =
      streamedAnswer ||
      (mode === 'direct'
        ? "I'm sorry, I couldn't generate a response."
        : 'I cannot find this information in the provided documents.')

    const botMessage = {
      role: 'assistant',
      content: answerContent,
      sources: normalizeSources(metadata.sources),
      responseTime,
      metadata: {
        ...metadata,
        mode,
        conversation_id: resolvedConversationId
      },
      retrievalScore: metadata.retrieval_score,
      corrected: metadata.was_corrected,
      attempts: metadata.correction_attempts
    }

    setMessages((prev) => [...prev, botMessage])
    setStreamingMessage('')
    if (onConversationActivity) onConversationActivity()
  }

  const handleFeedback = async (messageIndex, feedback) => {
    const message = messages[messageIndex]

    try {
      await axios.post(`${API_URL}/api/feedback`, {
        query: messages[messageIndex - 1]?.content || '',
        answer: message.content,
        feedback,
        sources: message.sources || [],
        response_time_ms: message.responseTime || 0
      })

      setMessages((prev) =>
        prev.map((msg, idx) =>
          idx === messageIndex ? { ...msg, userFeedback: feedback } : msg
        )
      )

      if (feedback === 0) {
        const confirmRetry = window.confirm(
          'Regenerate answer with a different approach?'
        )
        if (confirmRetry) {
          const originalQuery = messages[messageIndex - 1]?.content
          if (originalQuery) {
            setLoading(true)
            await handleStreamingQuery(originalQuery, Date.now())
            setLoading(false)
          }
        }
      } else {
        window.alert('Thanks for your feedback!')
      }
    } catch (error) {
      window.alert('Failed to submit feedback: ' + error.message)
    }
  }

  const handleUpload = async () => {
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    try {
      setLoading(true)
      const response = await axios.post(`${API_URL}/api/upload`, formData)
      window.alert(
        `Document "${file.name}" uploaded and indexed!\nChunks created: ${response.data.chunks}`
      )
      setFile(null)
      if (onDocumentChange) onDocumentChange()
    } catch (error) {
      window.alert(
        'Upload failed: ' + (error.response?.data?.detail || error.message)
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="chat-interface">
      <div className="chat-controls">
        <div className="control-group upload-group">
          <input
            type="file"
            accept=".pdf"
            onChange={(e) => setFile(e.target.files[0])}
            disabled={loading}
          />
          <button onClick={handleUpload} disabled={!file || loading}>
            📄 Upload & Index PDF
          </button>
        </div>

        <div className="control-group mode-group">
          <div className="mode-select-wrapper">
            <label htmlFor="mode-select">Response Mode</label>
            <select
              id="mode-select"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              disabled={loading}
            >
              <option value="fast">⚡ Fast - streaming RAG</option>
              <option value="quality">🎯 Quality - self correcting</option>
              <option value="direct">💬 Direct LLM (no documents)</option>
            </select>
          </div>
          <div className="mode-description">{MODE_DESCRIPTIONS[mode]}</div>
        </div>
      </div>

      <div className="chat-messages">
        {historyLoading && (
          <div className="history-loading">Loading conversation...</div>
        )}

        {!historyLoading && !conversationId && messages.length === 0 && (
          <div className="empty-chat-state">
            <p>Select a conversation from the sidebar or start a new chat.</p>
            <p className="hint">Chats are saved automatically.</p>
          </div>
        )}

        {!historyLoading && conversationId && messages.length === 0 && (
          <div className="empty-chat-state">
            <p>No messages yet.</p>
            <p className="hint">Ask the first question to get started.</p>
          </div>
        )}

        {messages.map((msg, idx) => {
          const sourceList = normalizeSources(msg.sources)
          return (
            <div key={msg.id || idx} className={`message ${msg.role}`}>
              <div className="message-content">{msg.content}</div>

              {msg.role === 'assistant' && !msg.userFeedback && (
                <div className="feedback-buttons">
                  <button
                    className="feedback-btn like"
                    onClick={() => handleFeedback(idx, 1)}
                    title="Good answer"
                  >
                    👍 Like
                  </button>
                  <button
                    className="feedback-btn dislike"
                    onClick={() => handleFeedback(idx, 0)}
                    title="Bad answer - Regenerate"
                  >
                    👎 Dislike
                  </button>
                </div>
              )}

              {msg.userFeedback === 1 && (
                <div className="feedback-indicator liked">
                  👍 You liked this response
                </div>
              )}
              {msg.userFeedback === 0 && (
                <div className="feedback-indicator disliked">
                  👎 You disliked this response
                </div>
              )}

              {msg.corrected && (
                <div className="correction-badge">
                  ✨ Self-corrected after {msg.attempts} attempt(s)
                </div>
              )}

              {msg.retrievalScore !== undefined && (
                <div className="score-badge">
                  📊 Retrieval Score: {(msg.retrievalScore * 100).toFixed(1)}%
                </div>
              )}

              {msg.responseTime && (
                <div className="time-badge">
                  ⏱️ Response time: {msg.responseTime.toFixed(0)} ms
                </div>
              )}

              {msg.metadata && msg.metadata.query_analysis && (
                <div className="metadata-badge">
                  Type: {msg.metadata.query_analysis.type} | Complexity:{' '}
                  {msg.metadata.query_analysis.complexity}
                </div>
              )}

              {sourceList.length > 0 && (
                <details className="sources">
                  <summary>📚 Sources ({sourceList.length})</summary>
                  {sourceList.map((src, sourceIdx) => {
                    const sourceText = asSourceText(src)
                    let filename = 'Document'
                    let page = '?'

                    const fileMatch =
                      sourceText.match(/(?:Source|File|Doc):\s*([^,\]\n]+)/i) ||
                      sourceText.match(/([a-zA-Z0-9_\-\s]+\.pdf)/i)

                    if (fileMatch) {
                      filename = fileMatch[1].trim()
                    }

                    const pageMatch =
                      sourceText.match(/(?:Page|Sayfa|p\.?)\s*[:#-]?\s*(\d+)/i) ||
                      sourceText.match(/---\s*PAGE\s*(\d+)\s*---/i)

                    if (pageMatch) {
                      page = pageMatch[1]
                    }

                    const cleanText = sourceText
                      .replace(/\[Source:.*?\]/g, '')
                      .replace(/---\s*PAGE\s*\d+\s*---/gi, '')
                      .trim()
                      .substring(0, 300)

                    return (
                      <div key={sourceIdx} className="source">
                        <strong className="source-citation">
                          [{filename.length > 25
                            ? `${filename.substring(0, 22)}...`
                            : filename}{' '}
                          - p.{page}]
                        </strong>
                        <p>{cleanText}...</p>
                      </div>
                    )
                  })}
                </details>
              )}
            </div>
          )
        })}

        {streamingMessage && (
          <div className="message assistant streaming">
            <div className="message-content">{streamingMessage}</div>
            <div className="typing-indicator">...</div>
          </div>
        )}

        {loading && !streamingMessage && (
          <div className="message assistant loading">
            <div className="loading-dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
            <span>Processing...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="chat-input">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !loading && handleSend()}
          placeholder="Ask a question about your documents..."
          disabled={loading}
        />
        <button onClick={handleSend} disabled={loading || !input.trim()}>
          {loading ? '...' : 'Send'}
        </button>
      </div>
    </div>
  )
}

export default ChatInterface