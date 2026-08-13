# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AudioInterview is a Japanese voice chat application that provides real-time speech recognition and AI-powered interview functionality. The application uses the Web Speech API for voice recognition and synthesis, and communicates with a remote AI interviewer API.

## Architecture

This is a client-side web application with the following structure:

- **index.html**: Main HTML file with Bootstrap-based UI including navigation controls, language selector, and chat container
- **src/js/script.js**: Core JavaScript functionality handling speech recognition, API communication, and chat interface
- **src/css/style.css**: Custom styling for the chat interface and responsive design

### Key Components

1. **Speech Recognition System**: Uses Web Speech API with configurable languages (Japanese, English, German) and automatic restart functionality
2. **Chat Interface**: Real-time message display with user/assistant message differentiation and chat history persistence
3. **API Integration**: Communicates with external interviewer API at `https://resilience-interviewer.onrender.com/audio_interview`
4. **Session Management**: Maintains session IDs and user IDs for conversation continuity
5. **Export Functionality**: Allows exporting chat history as JSON

### State Management

- Chat history is persisted in localStorage
- Session and user IDs are generated and maintained across browser sessions
- Speech recognition state is managed with visual feedback via navbar color changes

### Key Features

- **Silence Detection**: 3-second timeout for automatic speech recognition stopping
- **Continuous Recognition**: Auto-restart functionality for seamless conversation flow
- **Multi-language Support**: Japanese, English, and German speech recognition and synthesis
- **Visual Status Indicators**: Navbar changes color based on recognition state (waiting/recognizing/error)

## Development

This is a static web application - no build process or package manager is required. Simply open `index.html` in a web browser to run the application.

### Testing the Application

1. Serve the files using a local web server (required for speech recognition to work):
   ```bash
   python -m http.server 8000
   # or
   npx serve .
   ```

2. Navigate to `http://localhost:8000` in your browser

3. Click "開始" (Start) to begin voice recognition

### API Dependency

The application depends on the external API at `https://resilience-interviewer.onrender.com/audio_interview`. The API expects:
- `text`: User's spoken input
- `session_id`: Session identifier for conversation continuity
- `user_id`: User identifier

### Browser Requirements

- Modern browser with Web Speech API support (Chrome, Safari, Edge)
- Microphone access permissions required
- HTTPS or localhost required for speech recognition functionality