# Backend API Template

Modern REST API template built with Express.js and TypeScript.

## Tech Stack

- **Runtime**: Node.js
- **Framework**: Express.js 4.21+
- **Language**: TypeScript 5.9+
- **Database**: TCB managed PostgreSQL (via CloudBase JS SDK)
- **Validation**: Zod
- **Testing**: Jest + Supertest

## Project Structure

```
backend/
├── src/
│   ├── __tests__/             # Test files
│   ├── config/                # Configuration
│   │   ├── database.ts        # Database client
│   │   ├── env.ts             # Environment validation
│   │   └── logger.ts          # Pino logger setup
│   ├── middleware/            # Express middleware
│   │   ├── errorHandler.ts   # Error handling
│   │   ├── logger.ts          # HTTP logging
│   │   └── validation.ts     # Zod validation
│   ├── modules/               # Feature modules (routes + handlers)
│   │   └── system.ts          # System & health checks
│   ├── types/                 # TypeScript types & Zod schemas
│   ├── app.ts                 # Express app setup
│   └── index.ts               # Server entry point
├── .env.example               # Environment template
├── package.json
└── tsconfig.json
```

## Getting Started

### Prerequisites

- Node.js 18+
- npm or yarn

### Installation

1. Install dependencies:
```bash
cd backend
npm install
```

2. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your configuration
```

### Development

Start the development server with hot reload:
```bash
npm run dev
```

Server will start at `http://localhost:3000`

### Testing

Run tests:
```bash
npm test
```

Run tests in watch mode:
```bash
npm run test:watch
```

### Production Build

Build the project:
```bash
npm run build
```

Start production server:
```bash
npm start
```

## API Endpoints

### System Routes

- `GET /api/v1/` - API welcome message
- `GET /api/v1/health` - Basic health check
- `GET /api/v1/health/ready` - Readiness check (includes database connection)
- `GET /api/v1/health/live` - Liveness check
- `GET /api/v1/version` - API version information
- `GET /api/v1/ping` - Simple ping endpoint
- `GET /api/v1/status` - System status (uptime, memory, etc.)

### Your Domain Routes

Add your business logic as new modules in `src/modules/`. Each module combines routes and handlers in a single file for simplicity. See `src/modules/README.md` for detailed examples and best practices.

#### Quick Example

Create a new module `src/modules/user.ts`:

```typescript
import { Router } from 'express'
import { db } from '../config/database.js'

export const userRouter = Router()

userRouter.get('/', async (_req, res) => {
  const users = await db.collection('users').get()
  res.json(users.data)
})

userRouter.post('/', async (req, res) => {
  const result = await db.collection('users').add(req.body)
  res.status(201).json(result)
})
```

Register it in `src/app.ts`:

```typescript
import { userRouter } from './modules/user.js'
app.use(`${env.API_PREFIX}/users`, userRouter)
```

## API Examples

### Health Check
```bash
curl http://localhost:3000/api/v1/health
```

### Readiness Check
```bash
curl http://localhost:3000/api/v1/health/ready
```

### System Status
```bash
curl http://localhost:3000/api/v1/status
```

## Security Features

- **CORS**: Configured cross-origin resource sharing
- **Input Validation**: Zod schema validation
- **Error Handling**: Centralized error management

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `NODE_ENV` | Environment mode | `development` |
| `PORT` | Server port | `3000` |
| `API_PREFIX` | API route prefix | `/api/v1` |
| `CLOUDBASE_ENV_ID` | CloudBase environment ID | - |
| `CLOUDBASE_SECRET_ID` | CloudBase secret ID | - |
| `CLOUDBASE_SECRET_KEY` | CloudBase secret key | - |
| `CORS_ORIGIN` | Allowed CORS origin (URL or `*` for all) | `*` |

**Note on CORS:** Default is `*` (allow all origins). This disables credentials (cookies, authorization headers). For production, specify exact origins.

## Performance Optimizations

- Response compression
- Pagination for large datasets

## Error Handling

The API uses consistent error responses:

```json
{
  "status": "error",
  "message": "Error description",
  "errors": [] // Optional validation errors
}
```

HTTP Status Codes:
- `200` - Success
- `201` - Created
- `204` - No Content
- `400` - Bad Request
- `404` - Not Found
- `409` - Conflict
- `500` - Internal Server Error

## License

MIT
