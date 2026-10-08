#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef HRESULT (*QueryInterfaceFn)(void *, REFIID, LPVOID *);
typedef IOReturn (*GetDeviceProductFn)(void *, UInt16 *);
typedef IOReturn (*DeviceRequestFn)(void *, IOUSBDevRequest *);
typedef IOReturn (*DeviceRequestTOFn)(void *, IOUSBDevRequestTO *);
typedef IOReturn (*ReadPipeAsyncFn)(void *, UInt8, void *, UInt32, IOAsyncCallback1, void *);
typedef IOReturn (*ReadPipeAsyncTOFn)(void *, UInt8, void *, UInt32, UInt32, UInt32, IOAsyncCallback1, void *);

static QueryInterfaceFn original_query_interface = NULL;
// ponytail: this targets one attached camera; use per-interface state for multi-camera support.
static GetDeviceProductFn original_get_device_product = NULL;
static DeviceRequestFn original_device_request = NULL;
static DeviceRequestTOFn original_device_request_to = NULL;
static ReadPipeAsyncFn original_read_pipe_async = NULL;
static ReadPipeAsyncTOFn original_read_pipe_async_to = NULL;

typedef struct {
    IOAsyncCallback1 callback;
    void *refcon;
    void *buffer;
    UInt32 requested;
    UInt8 pipe;
} ReadContext;

static void patched_read_complete(void *opaque, IOReturn result, void *arg0) {
    ReadContext *context = opaque;
    uintptr_t actual = (uintptr_t)arg0;
    if (result == kIOReturnSuccess && context->pipe == 1 &&
        actual > 8 && actual < context->requested) {
        memset((char *)context->buffer + actual, 0, 8);
        actual += 8;
    }
    context->callback(context->refcon, result, (void *)actual);
    free(context);
}

static ReadContext *make_read_context(UInt8 pipe, void *buffer, UInt32 requested,
                                      IOAsyncCallback1 callback, void *refcon) {
    ReadContext *context = malloc(sizeof(*context));
    if (!context) return NULL;
    context->callback = callback;
    context->refcon = refcon;
    context->buffer = buffer;
    context->requested = requested;
    context->pipe = pipe;
    return context;
}

static IOReturn patched_read_pipe_async(void *self, UInt8 pipe, void *buffer, UInt32 size,
                                        IOAsyncCallback1 callback, void *refcon) {
    ReadContext *context = make_read_context(pipe, buffer, size, callback, refcon);
    if (!context) return kIOReturnNoMemory;
    IOReturn result = original_read_pipe_async(self, pipe, buffer, size,
                                                patched_read_complete, context);
    if (result != kIOReturnSuccess) free(context);
    return result;
}

static IOReturn patched_read_pipe_async_to(void *self, UInt8 pipe, void *buffer, UInt32 size,
                                           UInt32 no_data_timeout, UInt32 completion_timeout,
                                           IOAsyncCallback1 callback, void *refcon) {
    ReadContext *context = make_read_context(pipe, buffer, size, callback, refcon);
    if (!context) return kIOReturnNoMemory;
    IOReturn result = original_read_pipe_async_to(self, pipe, buffer, size,
                                                   no_data_timeout, completion_timeout,
                                                   patched_read_complete, context);
    if (result != kIOReturnSuccess) free(context);
    return result;
}

static void map_device_descriptor(UInt16 request_type, UInt16 request, UInt16 value,
                                  void *data, UInt32 length, IOReturn result) {
    if (result != kIOReturnSuccess || !data || length < sizeof(IOUSBDeviceDescriptor)) return;
    if ((request_type & 0x80) == 0 || request != kUSBRqGetDescriptor ||
        ((value >> 8) & 0xff) != kUSBDeviceDesc) return;
    IOUSBDeviceDescriptor *descriptor = (IOUSBDeviceDescriptor *)data;
    UInt16 product = USBToHostWord(descriptor->idProduct);
    if (product == 0xF556) {
        descriptor->idProduct = HostToUSBWord(0x1691);
    } else if (product == 0xF557) {
        descriptor->idProduct = HostToUSBWord(0x1692);
    }
}

static IOReturn spoofed_device_request(void *self, IOUSBDevRequest *request) {
    IOReturn result = original_device_request(self, request);
    map_device_descriptor(request->bmRequestType, request->bRequest, request->wValue,
                          request->pData, request->wLenDone, result);
    return result;
}

static IOReturn spoofed_device_request_to(void *self, IOUSBDevRequestTO *request) {
    IOReturn result = original_device_request_to(self, request);
    map_device_descriptor(request->bmRequestType, request->bRequest, request->wValue,
                          request->pData, request->wLenDone, result);
    return result;
}

static int is_usb_device_interface(REFIID iid) {
    CFUUIDRef uuid = CFUUIDCreateFromUUIDBytes(kCFAllocatorDefault, iid);
    if (!uuid) {
        return 0;
    }
    int result = CFEqual(uuid, kIOUSBDeviceInterfaceID) ||
                 CFEqual(uuid, kIOUSBDeviceInterfaceID500) ||
                 CFEqual(uuid, kIOUSBDeviceInterfaceID650) ||
                 CFEqual(uuid, kIOUSBDeviceInterfaceID942);
    CFRelease(uuid);
    return result;
}

static int is_usb_interface_interface(REFIID iid) {
    CFUUIDRef uuid = CFUUIDCreateFromUUIDBytes(kCFAllocatorDefault, iid);
    if (!uuid) return 0;
    int result = CFEqual(uuid, kIOUSBInterfaceInterfaceID) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID182) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID183) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID190) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID192) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID197) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID220) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID245) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID300) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID398) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID400) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID500) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID550) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID650) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID700) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID800) ||
                 CFEqual(uuid, kIOUSBInterfaceInterfaceID942);
    CFRelease(uuid);
    return result;
}

static IOReturn spoofed_get_device_product(void *self, UInt16 *product) {
    IOReturn result = original_get_device_product(self, product);
    if (result == kIOReturnSuccess && product) {
        if (*product == 0xF556) {
            *product = 0x1691;
        } else if (*product == 0xF557) {
            *product = 0x1692;
        }
    }
    return result;
}

static HRESULT wrapped_query_interface(void *self, REFIID iid, LPVOID *result_interface) {
    HRESULT result = original_query_interface(self, iid, result_interface);
    if (result || !result_interface || !*result_interface) {
        return result;
    }
    if (is_usb_interface_interface(iid)) {
        IOUSBInterfaceInterface **usb_interface = (IOUSBInterfaceInterface **)*result_interface;
        IOUSBInterfaceInterface *original_vtable = *usb_interface;
        original_read_pipe_async = original_vtable->ReadPipeAsync;
        original_read_pipe_async_to = original_vtable->ReadPipeAsyncTO;
        IOUSBInterfaceInterface *replacement_vtable = malloc(sizeof(*replacement_vtable));
        memcpy(replacement_vtable, original_vtable, sizeof(*replacement_vtable));
        replacement_vtable->ReadPipeAsync = patched_read_pipe_async;
        replacement_vtable->ReadPipeAsyncTO = patched_read_pipe_async_to;
        *usb_interface = replacement_vtable;
        return result;
    }
    if (!is_usb_device_interface(iid)) return result;
    IOUSBDeviceInterface **device = (IOUSBDeviceInterface **)*result_interface;
    IOUSBDeviceInterface *original_vtable = *device;
    if (!original_vtable || !original_vtable->GetDeviceProduct) {
        return result;
    }
    original_get_device_product = original_vtable->GetDeviceProduct;
    original_device_request = original_vtable->DeviceRequest;
    original_device_request_to = original_vtable->DeviceRequestTO;
    IOUSBDeviceInterface *replacement_vtable = malloc(sizeof(*replacement_vtable));
    memcpy(replacement_vtable, original_vtable, sizeof(*replacement_vtable));
    replacement_vtable->GetDeviceProduct = spoofed_get_device_product;
    replacement_vtable->DeviceRequest = spoofed_device_request;
    replacement_vtable->DeviceRequestTO = spoofed_device_request_to;
    *device = replacement_vtable;
    return result;
}

static CFTypeRef spoofed_create_property(io_registry_entry_t entry, CFStringRef key,
                                         CFAllocatorRef allocator, IOOptionBits options) {
    CFTypeRef value = IORegistryEntryCreateCFProperty(entry, key, allocator, options);
    if (!value || CFGetTypeID(value) != CFNumberGetTypeID()) {
        return value;
    }
    int product = 0;
    if (!CFNumberGetValue((CFNumberRef)value, kCFNumberIntType, &product)) {
        return value;
    }
    int mapped = 0;
    if (product == 0xF556) {
        mapped = 0x1691;
    } else if (product == 0xF557) {
        mapped = 0x1692;
    } else {
        return value;
    }
    CFRelease(value);
    return CFNumberCreate(allocator ? allocator : kCFAllocatorDefault, kCFNumberIntType, &mapped);
}

static IOReturn spoofed_create_plugin(io_service_t service, CFUUIDRef plugin_type,
                                      CFUUIDRef interface_type,
                                      IOCFPlugInInterface ***the_interface,
                                      SInt32 *the_score) {
    CFTypeRef value = IORegistryEntryCreateCFProperty(
        service, CFSTR("idProduct"), kCFAllocatorDefault, 0);
    int product = 0;
    if (value && CFGetTypeID(value) == CFNumberGetTypeID()) {
        CFNumberGetValue((CFNumberRef)value, kCFNumberIntType, &product);
    }
    if (value) {
        CFRelease(value);
    }
    IOReturn result = IOCreatePlugInInterfaceForService(
        service, plugin_type, interface_type, the_interface, the_score);
    if (product == 0xF556 || product == 0xF557) {
        if (result == kIOReturnSuccess && the_interface && *the_interface && **the_interface) {
            IOCFPlugInInterface **plugin = *the_interface;
            IOCFPlugInInterface *original_vtable = *plugin;
            original_query_interface = original_vtable->QueryInterface;
            IOCFPlugInInterface *replacement_vtable = malloc(sizeof(*replacement_vtable));
            memcpy(replacement_vtable, original_vtable, sizeof(*replacement_vtable));
            replacement_vtable->QueryInterface = wrapped_query_interface;
            *plugin = replacement_vtable;
        }
    }
    return result;
}

__attribute__((used)) static struct {
    const void *replacement;
    const void *replacee;
} interpose_create_property __attribute__((section("__DATA,__interpose"))) = {
    (const void *)spoofed_create_property,
    (const void *)IORegistryEntryCreateCFProperty,
};

__attribute__((used)) static struct {
    const void *replacement;
    const void *replacee;
} interpose_create_plugin __attribute__((section("__DATA,__interpose"))) = {
    (const void *)spoofed_create_plugin,
    (const void *)IOCreatePlugInInterfaceForService,
};
