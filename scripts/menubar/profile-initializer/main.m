#import <Foundation/Foundation.h>
#import <BuildConfig/BuildConfig.h>
#include <errno.h>
#include <stdio.h>
#include <sys/stat.h>

static int fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    return 1;
}

static BOOL realDirectory(NSString *path) {
    struct stat metadata;
    return lstat(path.fileSystemRepresentation, &metadata) == 0 && S_ISDIR(metadata.st_mode);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2) {
            return fail("One new destination directory is required.");
        }
        NSString *destination = [[NSFileManager defaultManager] stringWithFileSystemRepresentation:argv[1] length:strlen(argv[1])];
        if (![destination isAbsolutePath] || ![destination isEqualToString:destination.stringByStandardizingPath]) {
            return fail("The destination must be an absolute normalized path.");
        }
        NSString *parent = destination.stringByDeletingLastPathComponent;
        while (true) {
            if (!realDirectory(parent)) {
                return fail("A parent is missing, inaccessible, or symbolic.");
            }
            if ([parent isEqualToString:@"/"]) {
                break;
            }
            parent = parent.stringByDeletingLastPathComponent;
        }
        struct stat existing;
        if (lstat(destination.fileSystemRepresentation, &existing) == 0 || errno != ENOENT) {
            return fail("The destination already exists or cannot be checked; it was not changed.");
        }
        umask(0077);
        if (mkdir(destination.fileSystemRepresentation, 0700) != 0) {
            return fail("The new profile directory could not be created.");
        }
        NSString *accounts = [destination stringByAppendingPathComponent:@"accounts-metadata"];
        if (mkdir(accounts.fileSystemRepresentation, 0700) != 0) {
            return fail("The new account metadata directory could not be created.");
        }
        AppEncryptionParameters *parameters = [[AppEncryptionParameters alloc] initWithPath:destination];
        NSString *keyPath = [destination stringByAppendingPathComponent:@".tempkeyEncrypted"];
        struct stat metadata;
        if (lstat(keyPath.fileSystemRepresentation, &metadata) != 0 || !S_ISREG(metadata.st_mode) || metadata.st_size != 64 || chmod(keyPath.fileSystemRepresentation, 0600) != 0) {
            return fail("Native initialization did not create a regular 64-byte encrypted key.");
        }
        DeviceSpecificEncryptionParameters *first = [parameters decrypt];
        if (first == nil || first.key.length != 32 || first.salt.length != 16) {
            return fail("Native verification of the new encrypted key failed.");
        }
        NSData *encryptedBefore = [NSData dataWithContentsOfFile:keyPath];
        AppEncryptionParameters *reopened = [[AppEncryptionParameters alloc] initWithPath:destination];
        DeviceSpecificEncryptionParameters *second = [reopened decrypt];
        NSData *encryptedAfter = [NSData dataWithContentsOfFile:keyPath];
        if (second == nil || ![first.key isEqualToData:second.key] || ![first.salt isEqualToData:second.salt] || ![encryptedBefore isEqualToData:encryptedAfter] || [reopened hasPasscode]) {
            return fail("The new profile did not pass native reopen verification.");
        }
        puts("PROFILE_INITIALIZED");
        return 0;
    }
}
