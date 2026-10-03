#!/usr/bin/env python3
from pathlib import Path
import sys

repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
h_path = repo / "HDLGameSvr.h"
c_path = repo / "HDLGameSvr.c"

if not h_path.exists() or not c_path.exists():
    raise SystemExit("HDLGameSvr.h/HDLGameSvr.c not found")

h = h_path.read_text(encoding="utf-8")
c = c_path.read_text(encoding="utf-8")

if "HDLGMAN_SERVER_OPL_COVER_CAPS" in h or "OPLCOV1_MAX_COVER_SIZE" in c:
    raise SystemExit("OPLCOV1 already applied")

marker = "#define HDLGMAN_SERVER_VERSION 0x0C"
insert = r'''/* OPLCOV1 - custom OPL cover upload extension. */
struct OPLCoverStatReq
{
    char Startup[12]; /* E.g. \"SLUS_202.87\" + NUL */
} __attribute__((__packed__));

struct OPLCoverBeginReq
{
    char Startup[12]; /* E.g. \"SLUS_202.87\" + NUL */
    u32 length;
} __attribute__((__packed__));

'''
if marker not in h:
    raise SystemExit("header version marker not found")
h = h.replace(marker, insert + marker, 1)

marker = "    HDLGMAN_SERVER_SHUTDOWN = 0xFF,"
insert = r'''    // OPLCOV1 cover-art management (custom extension).
    HDLGMAN_SERVER_OPL_COVER_CAPS = 0x30,
    HDLGMAN_SERVER_OPL_COVER_STAT,
    HDLGMAN_SERVER_OPL_COVER_BEGIN,
    HDLGMAN_SERVER_OPL_COVER_DATA,
    HDLGMAN_SERVER_OPL_COVER_END,
    HDLGMAN_SERVER_OPL_COVER_CANCEL,

    HDLGMAN_SERVER_SHUTDOWN = 0xFF,'''
if marker not in h:
    raise SystemExit("header shutdown marker not found")
h = h.replace(marker, insert, 1)

old = r'''enum TASK_MODES {
    TASK_GAME_INSTALLATION = 0,
    TASK_OSD_RESOURCE_CONFIG,
    TASK_NONE = -1
};'''
new = r'''enum TASK_MODES {
    TASK_GAME_INSTALLATION = 0,
    TASK_OSD_RESOURCE_CONFIG,
    TASK_OPL_COVER,
    TASK_NONE = -1
};'''
if old not in c:
    raise SystemExit("TASK_MODES marker not found")
c = c.replace(old, new, 1)

marker = "enum THREAD_CMD {"
insert = r'''struct OPLCoverContext
{
    int fd;
    u32 expected;
    u32 received;
    char startup[12];
    char path[80];
};

'''
if marker not in c:
    raise SystemExit("THREAD_CMD marker not found")
c = c.replace(marker, insert + marker, 1)

marker = "static int CleanupClientConnection(struct ClientData *client);"
insert = r'''static int CancelOPLCover(struct ClientData *client, int removePartial);
static int OPLCoverCaps(struct ClientData *client, void *buffer, unsigned int length);
static int OPLCoverStat(struct ClientData *client, void *buffer, unsigned int length);
static int OPLCoverBegin(struct ClientData *client, void *buffer, unsigned int length);
static int OPLCoverData(struct ClientData *client, void *buffer, unsigned int length);
static int OPLCoverEnd(struct ClientData *client, void *buffer, unsigned int length);
static int OPLCoverCancel(struct ClientData *client, void *buffer, unsigned int length);
'''
if marker not in c:
    raise SystemExit("Cleanup prototype marker not found")
c = c.replace(marker, insert + marker, 1)

marker = "static int CleanupClientConnection(struct ClientData *client)\n{"
impl = r'''#define OPLCOV1_MAX_COVER_SIZE (4 * 1024 * 1024)
#define OPLCOV1_DIR_MODE 0777
#define OPLCOV1_FILE_MODE 0666

static int IsOPLStartupChar(char c)
{
    return (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
}

static int IsOPLStartupDigit(char c)
{
    return c >= '0' && c <= '9';
}

static int ValidateOPLStartup(const char *startup)
{
    int i;

    if (startup == NULL || startup[11] != '\0' || startup[4] != '_' || startup[8] != '.')
        return 0;

    for (i = 0; i < 4; i++) {
        if (!IsOPLStartupChar(startup[i]))
            return 0;
    }

    return IsOPLStartupDigit(startup[5]) &&
           IsOPLStartupDigit(startup[6]) &&
           IsOPLStartupDigit(startup[7]) &&
           IsOPLStartupDigit(startup[9]) &&
           IsOPLStartupDigit(startup[10]);
}

static int MountOPLCommon(void)
{
    int result;

    result = fileXioMount("pfs1:", "hdd0:__common", FIO_MT_RDWR);
    if (result < 0)
        return result;

    fileXioMkdir("pfs1:/OPL", OPLCOV1_DIR_MODE);
    fileXioMkdir("pfs1:/OPL/ART", OPLCOV1_DIR_MODE);
    return 0;
}

static void FinishOPLCoverTask(struct ClientData *client)
{
    client->status &= ~(CLIENT_STATUS_OPENED_FILE | CLIENT_STATUS_MOUNTED_FS);
    client->task = TASK_NONE;

    if (client->TaskData != NULL) {
        free(client->TaskData);
        client->TaskData = NULL;
    }

    SignalSema(RuntimeData.InstallationLockSema);
}

static int CancelOPLCover(struct ClientData *client, int removePartial)
{
    struct OPLCoverContext *ctx;

    if (client->task != TASK_OPL_COVER)
        return 0;

    ctx = (struct OPLCoverContext *)client->TaskData;
    if (ctx != NULL) {
        if (ctx->fd >= 0) {
            fileXioClose(ctx->fd);
            ctx->fd = -1;
        }

        if (removePartial && ctx->path[0] != '\0')
            fileXioRemove(ctx->path);

        fileXioSync("pfs1:", 0);
    }

    fileXioUmount("pfs1:");
    FinishOPLCoverTask(client);
    return 0;
}

static int OPLCoverCaps(struct ClientData *client, void *buffer, unsigned int length)
{
    static const char magic[] = "OPLCOV1";

    (void)buffer;
    if (length != 0)
        return SendResponse(client->socket, -EINVAL, NULL, 0);

    return SendResponse(client->socket, 0, magic, sizeof(magic) - 1);
}

static int OPLCoverStat(struct ClientData *client, void *buffer, unsigned int length)
{
    const struct OPLCoverStatReq *req = (const struct OPLCoverStatReq *)buffer;
    iox_stat_t stat;
    char path[80];
    int result;

    if (length != sizeof(struct OPLCoverStatReq) || !ValidateOPLStartup(req->Startup))
        return SendResponse(client->socket, -EINVAL, NULL, 0);

    WaitSema(client->StateSemaID);

    if (client->task != TASK_NONE || PollSema(RuntimeData.InstallationLockSema) != RuntimeData.InstallationLockSema) {
        SignalSema(client->StateSemaID);
        return SendResponse(client->socket, -EBUSY, NULL, 0);
    }

    result = MountOPLCommon();
    if (result >= 0) {
        snprintf(path, sizeof(path), "pfs1:/OPL/ART/%s_COV.jpg", req->Startup);
        result = (fileXioGetStat(path, &stat) >= 0) ? 1 : 0;
        fileXioUmount("pfs1:");
    }

    SignalSema(RuntimeData.InstallationLockSema);
    SignalSema(client->StateSemaID);
    return SendResponse(client->socket, result, NULL, 0);
}

static int OPLCoverBegin(struct ClientData *client, void *buffer, unsigned int length)
{
    const struct OPLCoverBeginReq *req = (const struct OPLCoverBeginReq *)buffer;
    struct OPLCoverContext *ctx;
    int result;

    if (length != sizeof(struct OPLCoverBeginReq) ||
        !ValidateOPLStartup(req->Startup) ||
        req->length == 0 || req->length > OPLCOV1_MAX_COVER_SIZE)
        return SendResponse(client->socket, -EINVAL, NULL, 0);

    WaitSema(client->StateSemaID);

    if (client->task != TASK_NONE || PollSema(RuntimeData.InstallationLockSema) != RuntimeData.InstallationLockSema) {
        SignalSema(client->StateSemaID);
        return SendResponse(client->socket, -EBUSY, NULL, 0);
    }

    ctx = malloc(sizeof(struct OPLCoverContext));
    if (ctx == NULL) {
        SignalSema(RuntimeData.InstallationLockSema);
        SignalSema(client->StateSemaID);
        return SendResponse(client->socket, -ENOMEM, NULL, 0);
    }

    memset(ctx, 0, sizeof(*ctx));
    ctx->fd = -1;
    ctx->expected = req->length;
    memcpy(ctx->startup, req->Startup, sizeof(ctx->startup));
    ctx->startup[sizeof(ctx->startup) - 1] = '\0';

    result = MountOPLCommon();
    if (result >= 0) {
        snprintf(ctx->path, sizeof(ctx->path), "pfs1:/OPL/ART/%s_COV.jpg", ctx->startup);
        ctx->fd = fileXioOpen(ctx->path, O_WRONLY | O_CREAT | O_TRUNC, OPLCOV1_FILE_MODE);
        if (ctx->fd >= 0) {
            client->TaskData = ctx;
            client->task = TASK_OPL_COVER;
            client->status |= CLIENT_STATUS_MOUNTED_FS | CLIENT_STATUS_OPENED_FILE;
            result = 0;
        } else {
            result = ctx->fd;
            fileXioUmount("pfs1:");
        }
    }

    if (result < 0) {
        free(ctx);
        SignalSema(RuntimeData.InstallationLockSema);
    }

    SignalSema(client->StateSemaID);
    return SendResponse(client->socket, result, NULL, 0);
}

static int OPLCoverData(struct ClientData *client, void *buffer, unsigned int length)
{
    struct OPLCoverContext *ctx;
    int result;

    WaitSema(client->StateSemaID);

    if (client->task != TASK_OPL_COVER || client->TaskData == NULL) {
        SignalSema(client->StateSemaID);
        return SendResponse(client->socket, -EINVAL, NULL, 0);
    }

    ctx = (struct OPLCoverContext *)client->TaskData;
    if (length == 0 || length > HDLGMAN_RECV_MAX || ctx->received + length > ctx->expected) {
        SignalSema(client->StateSemaID);
        return SendResponse(client->socket, -EINVAL, NULL, 0);
    }

    result = fileXioWrite(ctx->fd, buffer, length);
    if (result == (int)length) {
        ctx->received += length;
        result = 0;
    } else if (result >= 0) {
        result = -EIO;
    }

    SignalSema(client->StateSemaID);
    return SendResponse(client->socket, result, NULL, 0);
}

static int OPLCoverEnd(struct ClientData *client, void *buffer, unsigned int length)
{
    struct OPLCoverContext *ctx;
    int result;

    (void)buffer;
    if (length != 0)
        return SendResponse(client->socket, -EINVAL, NULL, 0);

    WaitSema(client->StateSemaID);

    if (client->task != TASK_OPL_COVER || client->TaskData == NULL) {
        SignalSema(client->StateSemaID);
        return SendResponse(client->socket, -EINVAL, NULL, 0);
    }

    ctx = (struct OPLCoverContext *)client->TaskData;
    if (ctx->received != ctx->expected) {
        CancelOPLCover(client, 1);
        SignalSema(client->StateSemaID);
        return SendResponse(client->socket, -EIO, NULL, 0);
    }

    result = fileXioClose(ctx->fd);
    ctx->fd = -1;

    if (result >= 0)
        result = fileXioSync("pfs1:", 0);

    if (fileXioUmount("pfs1:") < 0 && result >= 0)
        result = -EIO;

    FinishOPLCoverTask(client);
    SignalSema(client->StateSemaID);
    return SendResponse(client->socket, result < 0 ? result : 0, NULL, 0);
}

static int OPLCoverCancel(struct ClientData *client, void *buffer, unsigned int length)
{
    int result;

    (void)buffer;
    if (length != 0)
        return SendResponse(client->socket, -EINVAL, NULL, 0);

    WaitSema(client->StateSemaID);
    result = CancelOPLCover(client, 1);
    SignalSema(client->StateSemaID);
    return SendResponse(client->socket, result, NULL, 0);
}

'''
if marker not in c:
    raise SystemExit("Cleanup implementation marker not found")
c = c.replace(marker, impl + marker, 1)

old = r'''    switch (client->task) {
        case TASK_GAME_INSTALLATION:
            EndInstallation(client);
            break;
    }'''
new = r'''    switch (client->task) {
        case TASK_GAME_INSTALLATION:
            EndInstallation(client);
            break;
        case TASK_OPL_COVER:
            CancelOPLCover(client, 1);
            break;
    }'''
if old not in c:
    raise SystemExit("cleanup switch marker not found")
c = c.replace(old, new, 1)

marker = r'''            case HDLGMAN_SERVER_GET_FREE_SPACE:
                result = GetFreeSpace(client);
                break;'''
insert = marker + r'''
            case HDLGMAN_SERVER_OPL_COVER_CAPS:
                result = OPLCoverCaps(client, buffer, length);
                break;
            case HDLGMAN_SERVER_OPL_COVER_STAT:
                result = OPLCoverStat(client, buffer, length);
                break;
            case HDLGMAN_SERVER_OPL_COVER_BEGIN:
                result = OPLCoverBegin(client, buffer, length);
                break;
            case HDLGMAN_SERVER_OPL_COVER_DATA:
                result = OPLCoverData(client, buffer, length);
                break;
            case HDLGMAN_SERVER_OPL_COVER_END:
                result = OPLCoverEnd(client, buffer, length);
                break;
            case HDLGMAN_SERVER_OPL_COVER_CANCEL:
                result = OPLCoverCancel(client, buffer, length);
                break;'''
if marker not in c:
    raise SystemExit("HandlePacket free-space marker not found")
c = c.replace(marker, insert, 1)

h_path.write_text(h, encoding="utf-8")
c_path.write_text(c, encoding="utf-8")
print("OPLCOV1 patch applied")
