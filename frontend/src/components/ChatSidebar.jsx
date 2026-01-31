import React, { useState, useEffect } from 'react'
import axios from 'axios'
import './ChatSidebar.css'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function ChatSidebar({ currentConversationId, onSelectConversation, refreshTrigger }) {
  const [conversations, setConversations] = useState([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchConversations()
  }, [refreshTrigger])

  useEffect(() => {
    if (!loading && conversations.length > 0 && !currentConversationId && onSelectConversation) {
      onSelectConversation(conversations[0].id)
    }
  }, [loading, conversations, currentConversationId, onSelectConversation])

  const fetchConversations = async () => {
    try {
      setLoading(true)
      const response = await axios.get(`${API_URL}/api/conversations`)
      setConversations(response.data.conversations || [])
    } catch (error) {
      console.error('Failed to fetch conversations:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleNewChat = async () => {
    try {
      const response = await axios.post(`${API_URL}/api/conversations`, null, {
        params: { title: 'New Chat' }
      })
      
      const newId = response.data.conversation_id
      await fetchConversations()
      onSelectConversation(newId)
    } catch (error) {
      alert('Failed to create new chat: ' + error.message)
    }
  }

  const handleDeleteConversation = async (conversationId, e) => {
    e.stopPropagation()
    
    if (!confirm('Delete this conversation?')) return

    try {
      await axios.delete(`${API_URL}/api/conversations/${conversationId}`)
      await fetchConversations()
      
      if (conversationId === currentConversationId) {
        onSelectConversation(null)
      }
    } catch (error) {
      alert('Failed to delete conversation: ' + error.message)
    }
  }

  return (
    <div className="chat-sidebar">
      <div className="sidebar-header">
        <h2>💬 Chats</h2>
        <button className="new-chat-btn" onClick={handleNewChat}>
          ➕ New Chat
        </button>
      </div>

      <div className="conversations-list">
        {loading && <div className="loading-text">Loading chats...</div>}
        
        {!loading && conversations.length === 0 && (
          <div className="empty-state">
            <p>No conversations yet</p>
            <p className="hint">Start typing to create a chat</p>
          </div>
        )}

        {conversations.map((conv) => (
          <div
            key={conv.id}
            className={`conversation-item ${conv.id === currentConversationId ? 'active' : ''}`}
            onClick={() => onSelectConversation(conv.id)}
          >
            <div className="conversation-info">
              <div className="conversation-title">{conv.title}</div>
              <div className="conversation-meta">
                {conv.message_count} messages • {new Date(conv.updated_at).toLocaleDateString()}
              </div>
            </div>
            <div className="conversation-actions">
              <button
                className="delete-btn"
                onClick={(e) => handleDeleteConversation(conv.id, e)}
                title="Delete chat"
              >
                🗑️
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default ChatSidebar
